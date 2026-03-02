"""
Local Whisper transcription using faster-whisper.

Buffers audio chunks (100ms, int16 PCM 16kHz) and periodically runs
Whisper transcription in a background thread. Uses simple energy-based
VAD to detect speech pauses and emit on_utterance_end.

Models are stored in ~/.axel-assistant/models/<model_name>/
(CTranslate2 format: model.bin + config.json + tokenizer.json + vocabulary.json)
"""

import asyncio
import logging
import os
import numpy as np
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MODELS_DIR = Path.home() / ".axel-assistant" / "models"

# VAD thresholds
SILENCE_RMS_THRESHOLD = 300  # RMS below this = silence
SILENCE_CHUNKS_FOR_UTTERANCE_END = 15  # 15 * 100ms = 1.5s silence → utterance end
MIN_SPEECH_CHUNKS = 5  # At least 500ms of speech to trigger transcription
PROCESS_INTERVAL_CHUNKS = 30  # Process every 3 seconds max

# Global model cache: {model_name: WhisperModel}
_model_cache: dict = {}
_model_loading: dict[str, asyncio.Event] = {}
_model_error: dict[str, str] = {}


def is_model_ready(model_name: str) -> bool:
    """Check if a model is loaded and ready to use."""
    return model_name in _model_cache


def is_model_loading(model_name: str) -> bool:
    """Check if a model is currently being downloaded/loaded."""
    return model_name in _model_loading


def has_local_model(model_name: str) -> bool:
    """Check if model files exist locally."""
    return (MODELS_DIR / model_name / "model.bin").exists()


def get_model_status(model_name: str) -> str:
    """Get model status: ready / loading / error / available / not_downloaded."""
    if model_name in _model_cache:
        return "ready"
    if model_name in _model_loading:
        return "loading"
    if model_name in _model_error:
        return f"error: {_model_error[model_name]}"
    if has_local_model(model_name):
        return "available"  # Downloaded but not loaded into memory yet
    return "not_downloaded"


def _resolve_model_path(model_name: str) -> str:
    """Return local dir path if model exists locally, otherwise model name for HF download."""
    local_dir = MODELS_DIR / model_name
    model_bin = local_dir / "model.bin"
    if model_bin.exists():
        logger.info(f"Using local model: {local_dir}")
        return str(local_dir)
    # Fallback to huggingface_hub download (model name)
    return model_name


def _do_load_model(model_name: str):
    """Load WhisperModel in a thread (blocking)."""
    from faster_whisper import WhisperModel
    path = _resolve_model_path(model_name)
    return WhisperModel(path, device="cpu", compute_type="int8")


async def preload_model(model_name: str, on_status=None) -> None:
    """Pre-load a Whisper model into global cache. Safe to call concurrently.
    on_status: optional async callback(message) for progress updates."""
    if model_name in _model_cache:
        logger.info(f"Whisper model '{model_name}' already cached")
        return

    # If another coroutine is already loading this model, wait for it
    if model_name in _model_loading:
        logger.info(f"Waiting for Whisper model '{model_name}' (loading by another task)...")
        await _model_loading[model_name].wait()
        return

    event = asyncio.Event()
    _model_loading[model_name] = event
    _model_error.pop(model_name, None)
    try:
        logger.info(f"Loading Whisper model '{model_name}' (download + init)...")
        if on_status:
            await on_status(f"Загрузка модели Whisper ({model_name})...")
        model = await asyncio.to_thread(_do_load_model, model_name)
        _model_cache[model_name] = model
        logger.info(f"Whisper model '{model_name}' loaded and cached")
        if on_status:
            await on_status(None)  # Clear status
    except Exception as e:
        _model_error[model_name] = str(e)[:200]
        logger.error(f"Failed to load Whisper model '{model_name}': {e}")
        raise
    finally:
        event.set()
        _model_loading.pop(model_name, None)


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
        """Attach cached model and start processing."""
        self._label = label
        self._running = True
        self._buffer.clear()
        self._silence_count = 0
        self._speech_count = 0
        self._utterance_ended = False

        # Use globally cached model (must be preloaded before connect)
        if self.model_name in _model_cache:
            self._model = _model_cache[self.model_name]
            logger.info(f"Whisper [{label}]: using cached model '{self.model_name}'")
        else:
            # Fallback: load inline (shouldn't happen if preload was called)
            logger.warning(f"Whisper [{label}]: model not pre-loaded, loading now...")
            await preload_model(self.model_name)
            self._model = _model_cache[self.model_name]

        self._process_task = asyncio.create_task(self._process_loop())

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
