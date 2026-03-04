"""
Dual audio capture: microphone (user voice) + BlackHole (interviewer voice from Zoom/Teams).

Uses sounddevice for audio input and janus for thread-safe async queues
(sounddevice callbacks run in a C-level audio thread, not in asyncio event loop).

BlackHole is optional — if not installed, only microphone is captured.
"""

import sounddevice as sd
import numpy as np
import asyncio
import logging
import janus
from typing import Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BLOCK_SIZE = 1600  # 100ms at 16kHz


class AudioCapture:
    def __init__(self):
        self._mic_queue: Optional[janus.Queue] = None
        self._system_queue: Optional[janus.Queue] = None
        self._mic_stream: Optional[sd.InputStream] = None
        self._system_stream: Optional[sd.InputStream] = None
        self.is_recording = False
        self.has_system_audio = False

        # For resampling if device doesn't support 16kHz natively
        self._mic_native_rate: Optional[int] = None
        self._system_native_rate: Optional[int] = None

        # Diagnostic counters
        self._mic_chunk_count = 0
        self._system_chunk_count = 0

    @staticmethod
    def find_device(name_contains: str) -> int:
        """Find an audio input device by partial name match."""
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if name_contains.lower() in d['name'].lower() and d['max_input_channels'] > 0:
                return i
        raise ValueError(f"Audio device containing '{name_contains}' not found. "
                         f"Available devices: {[d['name'] for d in devices if d['max_input_channels'] > 0]}")

    @staticmethod
    def _find_any_mic() -> int:
        """Fallback: find any working input device (prefer MacBook, then Built-in)."""
        for name in ("MacBook", "Built-in"):
            try:
                return AudioCapture.find_device(name)
            except ValueError:
                continue
        # Last resort: first available input device
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if d['max_input_channels'] > 0 and 'blackhole' not in d['name'].lower():
                return i
        raise RuntimeError("No input audio device found")

    @staticmethod
    def list_input_devices() -> list[dict]:
        """List all available input devices."""
        devices = sd.query_devices()
        return [
            {"index": i, "name": d['name'], "channels": d['max_input_channels'],
             "sample_rate": d['default_samplerate']}
            for i, d in enumerate(devices) if d['max_input_channels'] > 0
        ]

    def _get_device_rate(self, device_idx: int) -> int:
        """Get native sample rate of a device."""
        info = sd.query_devices(device_idx)
        return int(info['default_samplerate'])

    def _resample(self, data: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Simple resample using numpy interpolation."""
        if from_rate == to_rate:
            return data
        duration = len(data) / from_rate
        new_length = int(duration * to_rate)
        indices = np.linspace(0, len(data) - 1, new_length)
        return np.interp(indices, np.arange(len(data)), data.astype(np.float32)).astype(np.int16)

    async def start(self):
        """Start capturing audio streams. BlackHole is optional."""
        self._mic_queue = janus.Queue()
        self._system_queue = janus.Queue()

        # Use system default input device (respects user's Sound settings)
        default_input = sd.default.device[0]
        if default_input is not None and default_input >= 0:
            mic_info = sd.query_devices(default_input)
            if mic_info['max_input_channels'] > 0:
                mic_idx = int(default_input)
                logger.info(f"Using system default input: [{mic_idx}] '{mic_info['name']}'")
            else:
                mic_idx = self._find_any_mic()
        else:
            mic_idx = self._find_any_mic()

        # BlackHole is optional — mic-only mode if not found
        blackhole_idx = None
        try:
            blackhole_idx = self.find_device("BlackHole")
        except ValueError:
            logger.warning("BlackHole not found — recording mic only (no system audio)")

        # Setup microphone stream
        self._mic_native_rate = self._get_device_rate(mic_idx)
        mic_block = int(self._mic_native_rate * 0.1)
        mic_info = sd.query_devices(mic_idx)
        logger.info(f"Mic device: [{mic_idx}] '{mic_info['name']}' native_rate={self._mic_native_rate}, block={mic_block}")
        self._mic_stream = sd.InputStream(
            device=mic_idx,
            channels=1,
            samplerate=self._mic_native_rate,
            dtype='int16',
            blocksize=mic_block,
            callback=self._mic_callback,
        )
        self._mic_stream.start()

        # Setup system audio stream (if BlackHole available)
        self.has_system_audio = blackhole_idx is not None
        if blackhole_idx is not None:
            self._system_native_rate = self._get_device_rate(blackhole_idx)
            system_block = int(self._system_native_rate * 0.1)
            self._system_stream = sd.InputStream(
                device=blackhole_idx,
                channels=1,
                samplerate=self._system_native_rate,
                dtype='int16',
                blocksize=system_block,
                callback=self._system_callback,
            )
            self._system_stream.start()

        self.is_recording = True

    def _mic_callback(self, indata, frames, time, status):
        """Callback for microphone — runs in audio thread."""
        if status:
            logger.warning(f"Mic audio status: {status}")
        if not self.is_recording:
            return
        audio = indata[:, 0].copy()
        if self._mic_native_rate != SAMPLE_RATE:
            audio = self._resample(audio, self._mic_native_rate, SAMPLE_RATE)
        raw = audio.tobytes()
        self._mic_chunk_count += 1
        if self._mic_chunk_count <= 3:
            peak = int(np.max(np.abs(audio)))
            logger.info(f"Mic callback #{self._mic_chunk_count}: {len(raw)} bytes, peak={peak}, dtype={audio.dtype}")
        self._mic_queue.sync_q.put_nowait(raw)

    def _system_callback(self, indata, frames, time, status):
        """Callback for system audio (BlackHole) — runs in audio thread."""
        if status:
            logger.warning(f"System audio status: {status}")
        if not self.is_recording:
            return
        audio = indata[:, 0].copy()
        if self._system_native_rate != SAMPLE_RATE:
            audio = self._resample(audio, self._system_native_rate, SAMPLE_RATE)
        raw = audio.tobytes()
        self._system_chunk_count += 1
        if self._system_chunk_count <= 3:
            peak = int(np.max(np.abs(audio)))
            logger.info(f"System callback #{self._system_chunk_count}: {len(raw)} bytes, peak={peak}, dtype={audio.dtype}")
        self._system_queue.sync_q.put_nowait(raw)

    @property
    def mic_queue(self) -> Optional[janus.Queue]:
        return self._mic_queue

    @property
    def system_queue(self) -> Optional[janus.Queue]:
        return self._system_queue

    def stop(self):
        """Stop recording and close streams."""
        self.is_recording = False
        if self._mic_stream:
            self._mic_stream.stop()
            self._mic_stream.close()
            self._mic_stream = None
        if self._system_stream:
            self._system_stream.stop()
            self._system_stream.close()
            self._system_stream = None
        # Close janus queues to unblock any waiting consumers
        if self._mic_queue:
            self._mic_queue.close()
            self._mic_queue = None
        if self._system_queue:
            self._system_queue.close()
            self._system_queue = None
