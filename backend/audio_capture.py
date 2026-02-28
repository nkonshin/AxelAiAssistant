"""
Dual audio capture: microphone (user voice) + BlackHole (interviewer voice from Zoom/Teams).

Uses sounddevice for audio input and janus for thread-safe async queues
(sounddevice callbacks run in a C-level audio thread, not in asyncio event loop).
"""

import sounddevice as sd
import numpy as np
import asyncio
import janus
from typing import Optional

SAMPLE_RATE = 16000
BLOCK_SIZE = 1600  # 100ms at 16kHz


class AudioCapture:
    def __init__(self):
        self._mic_queue: Optional[janus.Queue] = None
        self._system_queue: Optional[janus.Queue] = None
        self._mic_stream: Optional[sd.InputStream] = None
        self._system_stream: Optional[sd.InputStream] = None
        self.is_recording = False

        # For resampling if device doesn't support 16kHz natively
        self._mic_native_rate: Optional[int] = None
        self._system_native_rate: Optional[int] = None

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
        """Start capturing both audio streams."""
        self._mic_queue = janus.Queue()
        self._system_queue = janus.Queue()

        try:
            mic_idx = self.find_device("MacBook")
        except ValueError:
            # Fallback: try "Built-in" for older Macs
            mic_idx = self.find_device("Built-in")

        blackhole_idx = self.find_device("BlackHole")  # Raises if not installed

        self._mic_native_rate = self._get_device_rate(mic_idx)
        self._system_native_rate = self._get_device_rate(blackhole_idx)

        # Calculate block size for native rate to get ~100ms chunks
        mic_block = int(self._mic_native_rate * 0.1)
        system_block = int(self._system_native_rate * 0.1)

        self._mic_stream = sd.InputStream(
            device=mic_idx,
            channels=1,
            samplerate=self._mic_native_rate,
            dtype='int16',
            blocksize=mic_block,
            callback=self._mic_callback,
        )
        self._system_stream = sd.InputStream(
            device=blackhole_idx,
            channels=1,
            samplerate=self._system_native_rate,
            dtype='int16',
            blocksize=system_block,
            callback=self._system_callback,
        )

        self._mic_stream.start()
        self._system_stream.start()
        self.is_recording = True

    def _mic_callback(self, indata, frames, time, status):
        """Callback for microphone — runs in audio thread."""
        if not self.is_recording:
            return
        audio = indata[:, 0].copy()
        if self._mic_native_rate != SAMPLE_RATE:
            audio = self._resample(audio, self._mic_native_rate, SAMPLE_RATE)
        self._mic_queue.sync_q.put_nowait(bytes(audio))

    def _system_callback(self, indata, frames, time, status):
        """Callback for system audio (BlackHole) — runs in audio thread."""
        if not self.is_recording:
            return
        audio = indata[:, 0].copy()
        if self._system_native_rate != SAMPLE_RATE:
            audio = self._resample(audio, self._system_native_rate, SAMPLE_RATE)
        self._system_queue.sync_q.put_nowait(bytes(audio))

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
