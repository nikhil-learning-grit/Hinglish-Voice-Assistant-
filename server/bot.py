#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Midnight-Phantom-Hotline-Project - Production Resilient Pipecat Voice Agent

This bot implements a cascade pipeline with multi-provider fallbacks:
Speech-to-Text (STT) → LLM (with Gemini 2.5 Flash Fallback) → TTS (with Cartesia/OpenAI Fallback)

Configured Providers:
- Primary STT: Sarvam AI (model: saaras:v4, language: hi-IN for native Hinglish)
- Primary LLM: Groq (model: openai/gpt-oss-20b or qwen/qwen3.6-27b)
- Fallback LLM: Google Gemini (model: gemini-2.5-flash) for 429 rate limits & HTTP timeouts
- Primary TTS: Sarvam AI (model: bulbul:v4-flash, voice: meera / aparna / shubh)
- Fallback TTS: Cartesia (sonic-multilingual) or OpenAI Audio (tts-1) for >800ms latency or connection drops
- VAD: Continuous Silero VAD stream endpointing with immediate barge-in interruption handling

Run the bot using:
    uv run bot.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    CancelFrame,
    ErrorFrame,
    Frame,
    InterruptionFrame,
    LLMRunFrame,
    StartFrame,
    TextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

# Optional fallback service imports
try:
    from pipecat.services.google.llm import GoogleLLMService
except ImportError:
    GoogleLLMService = None

try:
    from pipecat.services.cartesia.tts import CartesiaTTSService
except ImportError:
    CartesiaTTSService = None

try:
    from pipecat.services.openai.tts import OpenAITTSService
except ImportError:
    OpenAITTSService = None

load_dotenv(override=True)

# The hospital data and business logic live at the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hospital_tools import (  # noqa: E402
    book_appointment,
    get_available_slots,
    get_hospital_information,
)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# -----------------------------------------------------------------------------
# Function Calling Tools
# -----------------------------------------------------------------------------

async def hospital_information(params: FunctionCallParams, topic: str):
    """Look up verified hospital information such as departments, timings, location, or FAQs.

    Args:
        topic: The user's question or a topic such as departments, timings, contact, policies, or OPD.
    """
    logger.info(f"Tool call: hospital_information(topic='{topic}')")
    result = get_hospital_information(topic)
    await params.result_callback(result)


async def available_appointment_slots(
    params: FunctionCallParams, specialization: str, date: str
):
    """Check real appointment availability for a department and date (YYYY-MM-DD).

    Args:
        specialization: Exact hospital department or doctor specialization (e.g., 'Cardiology', 'General Medicine').
        date: Appointment date in YYYY-MM-DD format.
    """
    logger.info(f"Tool call: available_appointment_slots(spec='{specialization}', date='{date}')")
    result = get_available_slots(specialization, date)
    await params.result_callback(result)


async def make_appointment(
    params: FunctionCallParams, patient_name: str, specialization: str, date: str, time_slot: str
):
    """Book a slot after the patient has provided all required details and availability was checked.

    Args:
        patient_name: Patient's full name.
        specialization: Hospital department or specialization.
        date: Appointment date in YYYY-MM-DD format.
        time_slot: Available time slot (e.g. '10:00 AM') returned by the availability lookup.
    """
    logger.info(
        f"Tool call: make_appointment(patient='{patient_name}', spec='{specialization}', date='{date}', slot='{time_slot}')"
    )
    result = book_appointment(patient_name, specialization, date, time_slot)
    await params.result_callback(result)


# -----------------------------------------------------------------------------
# Multi-Provider Resilient LLM Wrapper (Groq -> Gemini Fallback)
# -----------------------------------------------------------------------------

class ResilientLLMService(FrameProcessor):
    """Wraps primary Groq LLM with Google Gemini fallback to catch 429 rate-limits or HTTP timeouts."""

    def __init__(self, primary_llm, backup_llm=None):
        super().__init__()
        self._primary = primary_llm
        self._backup = backup_llm
        self._active_llm = self._primary
        self._fallback_active = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if not self._backup or self._fallback_active:
            await self._active_llm.process_frame(frame, direction)
            return

        try:
            await self._primary.process_frame(frame, direction)
        except Exception as exc:
            err_msg = str(exc).lower()
            if "429" in err_msg or "rate limit" in err_msg or "timeout" in err_msg or "timed out" in err_msg:
                logger.warning(
                    f"Primary Groq LLM experienced error ({exc}). Failing over to Google Gemini backup."
                )
                self._fallback_active = True
                self._active_llm = self._backup
                await self._backup.process_frame(frame, direction)
            else:
                raise exc


# -----------------------------------------------------------------------------
# Multi-Provider Resilient TTS Wrapper (Sarvam -> Cartesia/OpenAI Fallback)
# -----------------------------------------------------------------------------

class ResilientTTSService(FrameProcessor):
    """Wraps primary Sarvam TTS with fallback to Cartesia or OpenAI if latency > 800 ms or connection drops."""

    def __init__(self, primary_tts, fallback_tts=None, max_latency_seconds: float = 0.8):
        super().__init__()
        self._primary = primary_tts
        self._fallback = fallback_tts
        self._max_latency = max_latency_seconds
        self._active_tts = self._primary
        self._fallback_active = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if not self._fallback or self._fallback_active:
            await self._active_tts.process_frame(frame, direction)
            return

        start_time = time.perf_counter()
        try:
            if isinstance(frame, TextFrame):
                try:
                    await asyncio.wait_for(
                        self._primary.process_frame(frame, direction),
                        timeout=self._max_latency,
                    )
                except asyncio.TimeoutError:
                    elapsed = (time.perf_counter() - start_time) * 1000
                    logger.warning(
                        f"Sarvam AI TTS latency ({elapsed:.1f}ms) exceeded threshold ({self._max_latency*1000:.0f}ms). "
                        "Switching to backup TTS provider."
                    )
                    self._fallback_active = True
                    self._active_tts = self._fallback
                    await self._fallback.process_frame(frame, direction)
            else:
                await self._primary.process_frame(frame, direction)
        except Exception as exc:
            logger.warning(f"Sarvam AI TTS error ({exc}). Switching to backup audio provider.")
            self._fallback_active = True
            self._active_tts = self._fallback
            await self._fallback.process_frame(frame, direction)


# -----------------------------------------------------------------------------
# Main Voice Pipeline Setup
# -----------------------------------------------------------------------------

async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    """Run the resilient voice bot for this session."""
    logger.info("Initializing Midnight Phantom Hotline Voice Assistant")

    # Required API keys and configurations
    sarvam_api_key = _required_env("SARVAM_API_KEY")
    groq_api_key = _required_env("GROQ_API_KEY")
    groq_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    sarvam_voice_id = os.getenv("SARVAM_VOICE_ID", "meera")
    sarvam_stt_model = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
    sarvam_tts_model = os.getenv("SARVAM_TTS_MODEL", "bulbul:v4-flash")

    # 1. Primary Speech-to-Text (STT) - Sarvam saaras:v4 (Hinglish code-mixed)
    stt = SarvamSTTService(
        api_key=sarvam_api_key,
        model=sarvam_stt_model,
        language_code=os.getenv("SARVAM_STT_LANGUAGE", "hi-IN"),
    )

    # 2. Primary Speech Synthesis (TTS) - Sarvam bulbul:v4-flash
    primary_tts = SarvamTTSService(
        api_key=sarvam_api_key,
        settings=SarvamTTSService.Settings(
            model=sarvam_tts_model,
            voice=sarvam_voice_id,
        ),
    )

    # Optional Backup TTS (Cartesia sonic-multilingual or OpenAI tts-1)
    backup_tts = None
    cartesia_api_key = os.getenv("CARTESIA_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if CartesiaTTSService and cartesia_api_key:
        logger.info("Configuring Cartesia as backup audio output (TTS) provider")
        backup_tts = CartesiaTTSService(
            api_key=cartesia_api_key,
            settings=CartesiaTTSService.Settings(
                voice=os.getenv("CARTESIA_VOICE_ID", "sonic-multilingual"),
                model=os.getenv("CARTESIA_MODEL", "sonic-multilingual"),
            ),
        )
    elif OpenAITTSService and openai_api_key:
        logger.info("Configuring OpenAI Audio as backup audio output (TTS) provider")
        backup_tts = OpenAITTSService(
            api_key=openai_api_key,
            settings=OpenAITTSService.Settings(
                model=os.getenv("OPENAI_TTS_MODEL", "tts-1"),
                voice=os.getenv("OPENAI_VOICE_ID", "alloy"),
            ),
        )

    tts = ResilientTTSService(primary_tts=primary_tts, fallback_tts=backup_tts) if backup_tts else primary_tts

    # 3. System Instruction with Strict Tool Calling Guardrails
    system_instruction = (
        "You are the professional AI medical receptionist for Sanjeevani Multispeciality Hospital "
        "(Midnight Phantom Hotline). Speak naturally, politely, and concisely in English, Hindi, or Hinglish, "
        "matching the caller's language.\n\n"
        "RULES FOR SPOKEN OUTPUT:\n"
        "1. Your responses are spoken aloud over voice. NEVER output emojis, bullet points, asterisks, "
        "markdown tables, or formatting that cannot be spoken.\n"
        "2. Keep responses brief and conversational (1 to 2 sentences per turn).\n\n"
        "STRICT TOOL-CALLING LOGIC:\n"
        "1. NEVER invent hospital information, department locations, doctor names, or available slots.\n"
        "2. ALWAYS invoke `hospital_information` for facts about departments, timings, emergency services, or FAQs.\n"
        "3. ALWAYS invoke `available_appointment_slots` before attempting to book any appointment.\n"
        "4. Prompt the user for all four details (patient full name, department/specialization, date YYYY-MM-DD, "
        "and time slot) before calling `make_appointment`.\n"
        "5. ONLY confirm an appointment if `make_appointment` returns success: true with a valid booking reference.\n"
        "6. If booking fails or a slot is already booked, state the exact reason returned by the tool and offer "
        "alternative unbooked slots."
    )

    # 4. Primary LLM - Groq hosted model (openai/gpt-oss-20b or qwen/qwen3.6-27b)
    primary_llm = GroqLLMService(
        api_key=groq_api_key,
        settings=GroqLLMService.Settings(
            model=groq_model,
            system_instruction=system_instruction,
        ),
    )

    # Optional Fallback LLM - Google Gemini (gemini-2.5-flash)
    backup_llm = None
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if GoogleLLMService and gemini_api_key:
        logger.info("Configuring Google Gemini (gemini-2.5-flash) as automatic backup LLM provider")
        backup_llm = GoogleLLMService(
            api_key=gemini_api_key,
            settings=GoogleLLMService.Settings(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                system_instruction=system_instruction,
            ),
        )

    llm = ResilientLLMService(primary_llm=primary_llm, backup_llm=backup_llm) if backup_llm else primary_llm

    # 5. Function Calling Tools Registration
    context = LLMContext(
        tools=[hospital_information, available_appointment_slots, make_appointment]
    )

    # 6. Continuous Silero VAD stream endpointing and immediate barge-in interruption handling
    vad_analyzer = SileroVADAnalyzer(
        params=SileroVADAnalyzer.VADParams(
            stop_secs=0.5,
            start_secs=0.2,
            confidence=0.7,
        )
    )

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=vad_analyzer),
    )

    # 7. Pipeline Construction
    # Order: Transport Input -> STT -> User Context Aggregator -> LLM -> TTS -> Transport Output -> Assistant Aggregator
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[],
    )

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        context.add_message(
            {
                "role": "developer",
                "content": "Start by warmly and concisely introducing Sanjeevani Multispeciality Hospital and asking how you can help.",
            }
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected to Midnight Phantom Hotline voice session")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected from voice session")
        await runner.cancel()

    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Main bot entry point discovered by Pipecat runner."""
    transport_params = {
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    }

    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
