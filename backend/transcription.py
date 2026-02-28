"""
Deepgram Streaming API client for real-time speech transcription.

Two parallel WebSocket connections: one for microphone, one for system audio (BlackHole).
This way we know who is speaking without relying on diarization.
"""

import websockets
import json
import asyncio
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"


class DeepgramTranscriber:
    def __init__(
        self,
        api_key: str,
        on_transcript: Callable,
        on_utterance_end: Callable,
    ):
        self.api_key = api_key
        self.on_transcript = on_transcript
        self.on_utterance_end = on_utterance_end
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None

    async def connect(self, label: str = "system"):
        """Connect to Deepgram WebSocket streaming API."""
        params = (
            "?model=nova-3"
            "&language=ru"
            "&encoding=linear16"
            "&sample_rate=16000"
            "&channels=1"
            "&smart_format=true"
            "&interim_results=true"
            "&endpointing=300"
            "&utterance_end_ms=1000"
        )
        headers = {"Authorization": f"Token {self.api_key}"}

        self.ws = await websockets.connect(
            DEEPGRAM_WS_URL + params,
            extra_headers=headers,
            ping_interval=20,
        )
        self._receive_task = asyncio.create_task(self._receive_loop(label))
        logger.info(f"Deepgram connected [{label}]")

    async def send_audio(self, audio_bytes: bytes):
        """Send an audio chunk to Deepgram."""
        if self.ws and self.ws.open:
            await self.ws.send(audio_bytes)

    async def _receive_loop(self, label: str):
        """Receive and process responses from Deepgram."""
        try:
            async for msg in self.ws:
                data = json.loads(msg)

                # Final transcript of a complete phrase
                if data.get("is_final") and data.get("speech_final"):
                    alt = data.get("channel", {}).get("alternatives", [{}])[0]
                    transcript = alt.get("transcript", "")
                    if transcript.strip():
                        await self.on_transcript(label, 0, transcript)

                # Utterance end — long pause in speech
                if data.get("type") == "UtteranceEnd":
                    await self.on_utterance_end(label)

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"Deepgram WebSocket closed [{label}]: {e}")
        except Exception as e:
            logger.error(f"Deepgram receive error [{label}]: {e}")

    async def close(self):
        """Gracefully close the WebSocket connection."""
        if self._receive_task:
            self._receive_task.cancel()
            self._receive_task = None
        if self.ws:
            try:
                await self.ws.send(json.dumps({"type": "CloseStream"}))
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
