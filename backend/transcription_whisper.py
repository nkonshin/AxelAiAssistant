"""
Local Whisper transcription using faster-whisper.

Buffers audio chunks (100ms, int16 PCM 16kHz) and periodically runs
Whisper transcription in a background thread. Uses simple energy-based
VAD to detect speech pauses and emit on_utterance_end.
"""

import asyncio
import logging
import numpy as np
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# VAD thresholds
SILENCE_RMS_THRESHOLD = 300  # RMS below this = silence
SILENCE_CHUNKS_FOR_UTTERANCE_END = 15  # 15 * 100ms = 1.5s silence → utterance end
MIN_SPEECH_CHUNKS = 5  # At least 500ms of speech to trigger transcription
PROCESS_INTERVAL_CHUNKS = 30  # Process every 3 seconds max


class WhisperTranscriber:
    def __init__(
        self,
        model_name: str,
        on_transcript: Callable,
        on_utterance_end: Callable,
    ):
        self.model_name = model_name
        self.on_transcript = on_transcript
        self.on_utterance_end = on_utterance_end
        self._model = None
        self._buffer: list[bytes] = []
        self._label = "?"
        self._running = False
        self._process_task: Optional[asyncio.Task] = None
        self._silence_count = 0
        self._speech_count = 0
        self._utterance_ended = False

    async def connect(self, label: str = "system"):
        """Load the Whisper model (lazy, first call only)."""
        self._label = label
        self._running = True
        self._buffer.clear()
        self._silence_count = 0
        self._speech_count = 0
        self._utterance_ended = False

        if self._model is None:
            logger.info(f"Loading Whisper model '{self.model_name}' [{label}]...")
            self._model = await asyncio.to_thread(self._load_model)
            logger.info(f"Whisper model loaded [{label}]")
        else:
            logger.info(f"Whisper already loaded [{label}]")

        self._process_task = asyncio.create_task(self._process_loop())

    def _load_model(self):
        from faster_whisper import WhisperModel
        return WhisperModel(
            self.model_name,
            device="cpu",
            compute_type="int8",
        )

    async def send_audio(self, audio_bytes: bytes):
        """Buffer an audio chunk and track speech/silence."""
        if not self._running:
            return
        self._buffer.append(audio_bytes)

        # Simple energy-based VAD
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        rms = int(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))

        if rms < SILENCE_RMS_THRESHOLD:
            self._silence_count += 1
            # Detect utterance end: enough silence after speech
            if (
                self._speech_count >= MIN_SPEECH_CHUNKS
                and self._silence_count >= SILENCE_CHUNKS_FOR_UTTERANCE_END
                and not self._utterance_ended
            ):
                self._utterance_ended = True
                await self.on_utterance_end(self._label)
        else:
            self._silence_count = 0
            self._speech_count += 1
            self._utterance_ended = False

    async def _process_loop(self):
        """Periodically transcribe buffered audio."""
        while self._running:
            await asyncio.sleep(0.3)  # Check every 300ms

            # Process when: enough chunks AND either silence or max interval
            should_process = (
                len(self._buffer) >= MIN_SPEECH_CHUNKS
                and (
                    self._silence_count >= 8  # 800ms silence
                    or len(self._buffer) >= PROCESS_INTERVAL_CHUNKS
                )
                and self._speech_count >= MIN_SPEECH_CHUNKS
            )

            if should_process:
                await self._transcribe_buffer()

    async def _transcribe_buffer(self):
        """Run Whisper on accumulated audio buffer."""
        if not self._buffer or not self._model:
            return

        # Take current buffer and reset
        chunks = self._buffer[:]
        self._buffer.clear()
        self._speech_count = 0

        # Combine chunks into numpy array
        raw = b"".join(chunks)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

        if len(audio) < SAMPLE_RATE * 0.3:  # Skip < 300ms
            return

        try:
            segments, info = await asyncio.to_thread(
                self._model.transcribe,
                audio,
                beam_size=3,
                language="ru",
                vad_filter=True,
                vad_parameters={
                    "threshold": 0.4,
                    "min_silence_duration_ms": 500,
                },
                without_timestamps=True,
            )
            # Consume the generator in thread
            texts = await asyncio.to_thread(
                lambda: [s.text.strip() for s in segments if s.text.strip()]
            )
            if texts:
                full_text = " ".join(texts)
                logger.info(f"[{self._label}] whisper: {full_text[:80]}")
                await self.on_transcript(self._label, 0, full_text)
        except Exception as e:
            logger.error(f"Whisper transcription error [{self._label}]: {e}")

    async def close(self):
        """Stop processing and flush remaining audio."""
        self._running = False
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
            self._process_task = None

        # Transcribe any remaining buffered audio
        if self._buffer and self._model:
            await self._transcribe_buffer()

        self._buffer.clear()
