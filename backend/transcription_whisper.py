"""
Local Whisper transcription using pywhispercpp (whisper.cpp).

Buffers audio chunks (100ms, int16 PCM 16kHz) and periodically runs
Whisper transcription in a background thread. Uses simple energy-based
VAD to detect speech pauses and emit on_utterance_end.

GGML models are loaded from (in priority order):
  1. ~/.axel-assistant/models/ggml-<name>.bin
  2. ~/Library/Application Support/superwhisper/ggml-<name>.bin
  3. Auto-download by pywhispercpp (model name)
"""

import asyncio
import logging
import re
from collections import Counter
import numpy as np
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MODELS_DIR = Path.home() / ".axel-assistant" / "models"
SUPERWHISPER_DIR = Path.home() / "Library" / "Application Support" / "superwhisper"

# VAD thresholds
# Mic RMS is typically 500-5000+; system audio via BlackHole is much quieter (50-300).
# Using a low threshold to catch both sources reliably.
SILENCE_RMS_THRESHOLD = 80  # RMS below this = silence
SILENCE_CHUNKS_FOR_UTTERANCE_END = 15  # 15 * 100ms = 1.5s silence → utterance end
MIN_SPEECH_CHUNKS = 5  # At least 500ms of speech to trigger transcription
PROCESS_INTERVAL_CHUNKS = 30  # Process every 3 seconds max

# Known Whisper hallucination patterns (model artifacts from YouTube training data)
_HALLUCINATION_PATTERNS = [
    re.compile(r"продолжение\s+следует", re.IGNORECASE),
    re.compile(r"субтитры\s+(сделал|делал|создал|создавал|подготовил)\s+\w+", re.IGNORECASE),
    re.compile(r"подписывайтесь\s+на\s+канал", re.IGNORECASE),
    re.compile(r"ставьте\s+лайк", re.IGNORECASE),
    re.compile(r"редактор\s+субтитров", re.IGNORECASE),
    re.compile(r"www\.\w+\.\w+", re.IGNORECASE),
    re.compile(r"\.{3,}"),  # Repeated ellipsis (...)
]


def _is_hallucination(text: str) -> bool:
    """Check if text matches known Whisper hallucination patterns."""
    for pattern in _HALLUCINATION_PATTERNS:
        if pattern.search(text):
            return True

    # Detect repetitive text: split into words and check if >60% are the same word
    words = text.lower().split()
    if len(words) >= 3:
        counts = Counter(words)
        most_common_count = counts.most_common(1)[0][1]
        if most_common_count / len(words) > 0.5:
            return True

    return False


# Global model cache: {model_name: Model}
_model_cache: dict = {}
_model_loading: dict[str, asyncio.Event] = {}
_model_error: dict[str, str] = {}

# Global lock: whisper.cpp uses Metal GPU which can't handle concurrent
# command buffers from multiple model instances. Serialize all transcribe() calls.
_transcribe_lock = asyncio.Lock()


def is_model_ready(model_name: str) -> bool:
    """Check if a model is loaded and ready to use."""
    return model_name in _model_cache


def is_model_loading(model_name: str) -> bool:
    """Check if a model is currently being downloaded/loaded."""
    return model_name in _model_loading


def _find_ggml_file(model_name: str) -> Optional[Path]:
    """Find a GGML model file on disk. Returns path or None."""
    # 1. Explicit: ~/.axel-assistant/models/ggml-<name>.bin
    p = MODELS_DIR / f"ggml-{model_name}.bin"
    if p.exists():
        return p

    # 2. Superwhisper: ~/Library/Application Support/superwhisper/ggml-<name>.bin
    p = SUPERWHISPER_DIR / f"ggml-{model_name}.bin"
    if p.exists():
        return p

    return None


def has_local_model(model_name: str) -> bool:
    """Check if GGML model file exists locally."""
    return _find_ggml_file(model_name) is not None


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


def _do_load_model(model_name: str):
    """Load pywhispercpp Model in a thread (blocking)."""
    from pywhispercpp.model import Model

    common_params = dict(
        n_threads=6,
        print_progress=False,
        print_realtime=False,
        print_timestamps=False,
        language="ru",
        # No initial_prompt — it causes hallucinations (Whisper repeats prompt
        # keywords like "Python, Python, Python" during silence).
        no_speech_thold=0.4,  # Stricter no-speech threshold to reduce hallucinations
    )
    local_path = _find_ggml_file(model_name)
    if local_path:
        logger.info(f"Loading GGML model from: {local_path}")
        return Model(str(local_path), redirect_whispercpp_logs_to="/dev/null", **common_params)
    else:
        # pywhispercpp auto-downloads by model name
        logger.info(f"No local GGML found, auto-downloading '{model_name}'...")
        return Model(model_name, redirect_whispercpp_logs_to="/dev/null", **common_params)


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
        logger.info(f"Loading Whisper model '{model_name}'...")
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
        self._chunk_count = 0

    async def connect(self, label: str = "system"):
        """Attach shared model and start processing.

        All transcribers share one model instance to avoid Metal GPU conflicts.
        Concurrent transcribe() calls are serialized via _transcribe_lock.
        """
        self._label = label
        self._running = True
        self._buffer.clear()
        self._silence_count = 0
        self._speech_count = 0
        self._utterance_ended = False

        # Use globally cached model (must be preloaded before connect)
        if self.model_name not in _model_cache:
            logger.warning(f"Whisper [{label}]: model not pre-loaded, loading now...")
            await preload_model(self.model_name)

        self._model = _model_cache[self.model_name]
        logger.info(f"Whisper [{label}]: using shared model '{self.model_name}'")

        self._process_task = asyncio.create_task(self._process_loop())

    async def send_audio(self, audio_bytes: bytes):
        """Buffer an audio chunk and track speech/silence."""
        if not self._running:
            return
        self._buffer.append(audio_bytes)

        # Simple energy-based VAD
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        rms = int(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))

        # Log RMS for first 10 speech chunks to help diagnose audio levels
        self._chunk_count += 1
        if self._chunk_count <= 5 or (self._chunk_count <= 100 and rms > SILENCE_RMS_THRESHOLD and self._speech_count < 10):
            logger.info(f"[{self._label}] VAD chunk #{self._chunk_count}: rms={rms}, threshold={SILENCE_RMS_THRESHOLD}")

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

        # Combine chunks into numpy float32 array (whisper.cpp expects float32)
        raw = b"".join(chunks)
        audio_int16 = np.frombuffer(raw, dtype=np.int16)

        # Check buffer energy: skip if mostly silence (prevents hallucinations on quiet audio)
        rms = int(np.sqrt(np.mean(audio_int16.astype(np.float64) ** 2)))
        if rms < SILENCE_RMS_THRESHOLD:
            logger.debug(f"[{self._label}] skipping quiet buffer (RMS={rms})")
            return

        audio = audio_int16.astype(np.float32) / 32768.0

        if len(audio) < SAMPLE_RATE * 0.3:  # Skip < 300ms
            return

        try:
            # Serialize transcription calls: Metal GPU can't handle concurrent
            # command buffers, and whisper.cpp model is not thread-safe.
            async with _transcribe_lock:
                segments = await asyncio.to_thread(
                    self._model.transcribe, audio
                )
            texts = [s.text.strip() for s in segments if s.text.strip()]
            if texts:
                full_text = " ".join(texts)
                # Filter out known Whisper hallucinations
                if _is_hallucination(full_text):
                    logger.info(f"[{self._label}] filtered hallucination: {full_text[:60]}")
                    return
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
        try:
            if self._buffer and self._model:
                await self._transcribe_buffer()
        finally:
            self._buffer.clear()
