import { PipecatClient, RTVIEvent } from '@pipecat-ai/client-js';
import {
  DEFAULT_TRANSPORT,
  PROJECT_NAME,
  TRANSPORT_CONFIG,
  createTransport,
} from './config';

class HotlineVoiceClient {
  constructor() {
    this.client = null;
    this.transportType = DEFAULT_TRANSPORT;
    this.isConnected = false;
    this.audioElement = null;

    // Real-time Audio Analyser for organic ripple effects
    this.audioContext = null;
    this.analyser = null;
    this.audioSourceNode = null;
    this.animFrameId = null;

    // Latency & State Tracking
    this.currentState = 'idle';
    this.userSpeechEndTime = null;
    this.llmStartTime = null;
    this.botSpeechStartTime = null;

    this.setupDOM();
    this.setupEventListeners();
  }

  setupDOM() {
    document.title = PROJECT_NAME ? `${PROJECT_NAME} — AI Reception` : 'Midnight Phantom Hotline — AI Reception';

    // Header elements
    this.statusBadge = document.getElementById('status-badge');
    this.badgeText = document.getElementById('badge-text');
    this.latStt = document.getElementById('lat-stt');
    this.latLlm = document.getElementById('lat-llm');
    this.latTts = document.getElementById('lat-tts');
    this.latE2e = document.getElementById('lat-e2e');

    // Central Stage elements
    this.boundary = document.getElementById('visualizer-boundary');
    this.mainMicBtn = document.getElementById('main-mic-btn');
    this.iconActive = document.getElementById('icon-mic-active');
    this.iconMuted = document.getElementById('icon-mic-muted');
    this.subPrompt = document.getElementById('sub-prompt');

    // Auxiliary controls
    this.btnMute = document.getElementById('btn-mute');
    this.muteLabel = document.getElementById('mute-label');
    this.btnReset = document.getElementById('btn-reset');
    this.btnDisconnect = document.getElementById('btn-disconnect');

    this.setSystemState('idle', 'Tap to start speaking');
  }

  setupEventListeners() {
    // 1. Central Neumorphic Microphone Button - toggle capture & connect
    this.mainMicBtn.addEventListener('click', () => {
      if (!this.isConnected) {
        this.connect();
      } else if (this.client) {
        this.toggleMic();
      }
    });

    // 2. Auxiliary Mute Button
    this.btnMute.addEventListener('click', () => {
      if (this.isConnected && this.client) {
        this.toggleMic();
      }
    });

    // 3. Auxiliary Reset Session Button
    this.btnReset.addEventListener('click', () => {
      if (this.isConnected && this.client) {
        this.resetSession();
      }
    });

    // 4. Auxiliary End Call Button
    this.btnDisconnect.addEventListener('click', () => {
      if (this.isConnected) {
        this.disconnect();
      }
    });
  }

  toggleMic() {
    if (!this.client) return;
    const newState = !this.client.isMicEnabled;
    this.client.enableMic(newState);
    this.updateMicVisuals(newState);
  }

  updateMicVisuals(isMicEnabled) {
    if (isMicEnabled) {
      this.iconActive.classList.remove('hidden');
      this.iconMuted.classList.add('hidden');
      this.btnMute.classList.remove('active');
      this.muteLabel.textContent = 'Mute Mic';
      if (this.currentState === 'idle') {
        this.setSystemState('idle', 'Listening for your query...');
      }
    } else {
      this.iconActive.classList.add('hidden');
      this.iconMuted.classList.remove('hidden');
      this.btnMute.classList.add('active');
      this.muteLabel.textContent = 'Unmute Mic';
      this.setSystemState('idle', 'Microphone paused. Tap to resume.');
    }
  }

  setSystemState(state, captionText) {
    this.currentState = state;

    // Reset boundary classes
    this.boundary.classList.remove(
      'state-idle',
      'state-user-speaking',
      'state-bot-speaking'
    );

    // Reset badge classes
    this.statusBadge.classList.remove(
      'badge-ready',
      'badge-connecting',
      'badge-listening',
      'badge-speaking'
    );

    switch (state) {
      case 'listening':
      case 'user-speaking':
        this.boundary.classList.add('state-user-speaking');
        this.statusBadge.classList.add('badge-listening');
        this.badgeText.textContent = 'Listening...';
        break;

      case 'speaking':
      case 'bot-speaking':
        this.boundary.classList.add('state-bot-speaking');
        this.statusBadge.classList.add('badge-speaking');
        this.badgeText.textContent = 'Speaking...';
        break;

      case 'connecting':
        this.boundary.classList.add('state-idle');
        this.statusBadge.classList.add('badge-connecting');
        this.badgeText.textContent = 'Connecting...';
        break;

      case 'idle':
      default:
        this.boundary.classList.add('state-idle');
        this.statusBadge.classList.add('badge-ready');
        this.badgeText.textContent = 'Ready';
        break;
    }

    if (captionText) {
      this.subPrompt.textContent = captionText;
    }
  }

  async connect() {
    try {
      this.setSystemState('connecting', 'Connecting to Sanjeevani Reception...');
      this.mainMicBtn.disabled = true;

      const transport = await createTransport(this.transportType);

      this.client = new PipecatClient({
        transport,
        enableMic: true,
        enableCam: false,
        callbacks: {
          onConnected: () => {
            this.onConnected();
          },
          onDisconnected: () => {
            this.onDisconnected();
          },
          onTransportStateChanged: (state) => {
            console.log('Transport state changed:', state);
          },
          onBotReady: () => {
            this.setSystemState('idle', 'Ready — ask anything in Hindi or English');
          },
          onUserStartedSpeaking: () => {
            this.userSpeechEndTime = null;
            this.setSystemState('user-speaking', 'Listening to you...');
          },
          onUserStoppedSpeaking: () => {
            this.userSpeechEndTime = Date.now();
            if (this.isConnected && this.currentState === 'user-speaking') {
              this.setSystemState('idle', 'Thinking...');
            }
          },
          onUserTranscript: (data) => {
            if (data?.final && this.userSpeechEndTime) {
              const sttMs = Math.max(1, Date.now() - this.userSpeechEndTime);
              this.latStt.textContent = `${sttMs} ms`;
            }
          },
          onBotLlmStarted: () => {
            this.llmStartTime = Date.now();
            this.setSystemState('idle', 'Thinking...');
          },
          onBotStartedSpeaking: () => {
            const now = Date.now();
            this.botSpeechStartTime = now;

            if (this.llmStartTime) {
              const llmMs = Math.max(1, now - this.llmStartTime);
              this.latLlm.textContent = `${llmMs} ms`;
            }

            if (this.userSpeechEndTime) {
              const e2eMs = Math.max(1, now - this.userSpeechEndTime);
              this.latE2e.textContent = `${e2eMs} ms`;
            }

            this.setSystemState('bot-speaking', 'Sanjeevani Reception is speaking...');
          },
          onBotStoppedSpeaking: () => {
            if (this.isConnected) {
              this.setSystemState('idle', 'Ready — ask your next question');
            }
          },
          onError: (error) => {
            const msg = error?.message || String(error);
            console.error('Voice stream error:', msg);
            this.setSystemState('idle', `Error: ${msg}`);
          },
        },
      });

      this.setupAudio();

      const connectParams = TRANSPORT_CONFIG[this.transportType];
      if (this.transportType === 'websocket') {
        const { wsUrl, token } = await this.client.startBot(connectParams);
        await this.client.connect({
          wsUrl: token ? `${wsUrl}?token=${encodeURIComponent(token)}` : wsUrl,
        });
      } else {
        await this.client.startBotAndConnect(connectParams);
      }
    } catch (err) {
      const msg = err?.message || String(err);
      console.error('Connection failed:', err);
      this.setSystemState('idle', `Connection failed: ${msg}`);
      this.mainMicBtn.disabled = false;
    }
  }

  async disconnect() {
    if (this.client) {
      try {
        await this.client.disconnect();
      } catch (err) {
        console.warn('Disconnect error:', err);
      }
      this.client = null;
    }
    this.onDisconnected();
  }

  async resetSession() {
    this.setSystemState('connecting', 'Reconnecting session...');
    if (this.client) {
      try {
        await this.client.disconnect();
      } catch (err) {
        console.warn('Reset error:', err);
      }
      this.client = null;
    }
    await this.connect();
  }

  setupAudio() {
    this.client.on(RTVIEvent.TrackStarted, (track, participant) => {
      if (!participant?.local && track.kind === 'audio') {
        const ttsStart = Date.now();
        if (this.botSpeechStartTime) {
          const ttsMs = Math.max(1, ttsStart - this.botSpeechStartTime);
          this.latTts.textContent = `${ttsMs} ms`;
        }

        if (!this.audioElement) {
          this.audioElement = document.createElement('audio');
          this.audioElement.autoplay = true;
          this.audioElement.playsInline = true;
          document.body.appendChild(this.audioElement);
        }
        this.audioElement.srcObject = new MediaStream([track]);
        this.audioElement.play().catch((err) => {
          console.warn('Playback request error:', err);
        });

        this.attachAudioVisualizer(track);
      }
    });
  }

  attachAudioVisualizer(mediaStreamTrack) {
    try {
      if (!this.audioContext) {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        this.audioContext = new AudioCtx();
      }
      if (this.audioContext.state === 'suspended') {
        this.audioContext.resume();
      }

      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 64;
      this.analyser.smoothingTimeConstant = 0.8;

      const stream = new MediaStream([mediaStreamTrack]);
      this.audioSourceNode = this.audioContext.createMediaStreamSource(stream);
      this.audioSourceNode.connect(this.analyser);

      this.startVisualizerLoop();
    } catch (err) {
      console.warn('Audio visualizer analyser attachment:', err);
    }
  }

  startVisualizerLoop() {
    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId);
    }

    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);

    const renderPulse = () => {
      if (this.analyser && this.currentState === 'bot-speaking') {
        this.analyser.getByteFrequencyData(dataArray);

        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          sum += dataArray[i];
        }
        const avg = sum / dataArray.length;
        const normalized = Math.min(avg / 128, 1);

        // Fluid organic scale wave based on real vocal audio
        const scale = 1 + normalized * 0.18;
        this.boundary.style.transform = `scale(${scale.toFixed(3)})`;
      } else if (this.currentState !== 'user-speaking') {
        this.boundary.style.transform = '';
      }

      this.animFrameId = requestAnimationFrame(renderPulse);
    };

    renderPulse();
  }

  onConnected() {
    this.isConnected = true;
    this.mainMicBtn.disabled = false;
    this.btnMute.disabled = false;
    this.btnReset.disabled = false;
    this.btnDisconnect.disabled = false;

    this.updateMicVisuals(this.client.isMicEnabled);
    this.setSystemState('idle', 'Ready — ask anything in Hindi or English');
  }

  onDisconnected() {
    this.isConnected = false;
    this.mainMicBtn.disabled = false;
    this.btnMute.disabled = true;
    this.btnReset.disabled = true;
    this.btnDisconnect.disabled = true;

    this.updateMicVisuals(true);
    this.setSystemState('idle', 'Tap to start speaking');

    // Reset latency metrics
    this.latStt.textContent = '-- ms';
    this.latLlm.textContent = '-- ms';
    this.latTts.textContent = '-- ms';
    this.latE2e.textContent = '-- ms';

    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }
    if (this.boundary) {
      this.boundary.style.transform = '';
    }
  }
}

// Bootstrap when DOM content is ready
window.addEventListener('DOMContentLoaded', () => {
  new HotlineVoiceClient();
});
