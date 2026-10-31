# Hinglish Voice Assistant

A real-time, browser-based Hinglish voice assistant built for hospital appointment scheduling and administration queries, designed to handle code-switching, barge-in interruptions, and low-bandwidth conditions.

## Overview

The Midnight Phantom Hotline is a two-person hackathon project developed to demonstrate a dependable, low-latency voice AI pipeline.

The system allows users to converse naturally in Hindi, English, or code-mixed Hinglish to check hospital information, look up doctor availability, and book appointments without filling out forms.

## Key Features

- **Multilingual Natural Language Understanding:** Seamlessly processes and responds in Hindi, English, and natural Hinglish.
- **Core Hospital Tools (`hospital_tools.py`):** Deterministic backend logic handling hospital FAQs, doctor slot filtering, and appointment booking with atomic file locking and double-booking prevention.
- **Barge-In / Interruption Support:** Allows users to speak over the assistant to correct requests mid-conversation.
- **Network Resilience:** Optimized for audio-first, low-payload performance compatible with browser network throttling (Fast/Slow 3G simulation).
- **Strict Validation & Guardrails:** Ensures the LLM acts strictly through tool-calling and never fabricates booking confirmations or slot availability.

## Architecture & Project Structure

```text
midnight-phantom-hotline/
├── bot.py                  # Voice pipeline and LLM orchestration (Chinmay)
├── hospital_tools.py       # Hospital information and booking backend (Nikhil)
├── data/
│   ├── hospital.json       # Hospital metadata, timings, and bilingual FAQs
│   ├── doctors.json        # Mock doctor profiles and specializations
│   └── appointments.json   # Initial schedule slots and pre-booked test states
├── tests/
│   └── test_hospital.py    # Comprehensive automated test suite (17 test cases)
├── .env.example            # Template for environment variables
├── .gitignore              # Excludes sensitive keys, venv, and cache files
└── README.md
```

## Setup & Installation

### 1. Clone the repository

```bash
git clone https://github.com/nikhil-learning-grit/Hinglish-Voice-Assistant-.git
cd Hinglish-Voice-Assistant-
```

### 2. Set up a virtual environment

```bash
python -m venv venv
```

Activate it:

**Linux / macOS:**
```bash
source venv/bin/activate
```

**Windows:**
```bash
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root based on `.env.example` and add your required provider API keys (e.g., Groq, Sarvam AI).

**Important:** Never commit your `.env` file to GitHub.

## Running the Tests

To run the backend test suite and verify booking logic, data integrity, and concurrency handling:

```bash
pytest tests/test_hospital.py
```

## Running the Application

Start the local voice pipeline server:

```bash
python bot.py
```

Open the provided local URL in your Chrome browser, grant microphone permissions, and begin speaking in Hindi, English, or Hinglish.