"""
Deepgram Streaming API client for real-time speech transcription.

Two parallel WebSocket connections: one for microphone, one for system audio (BlackHole).
This way we know who is speaking without relying on diarization.
"""

import websockets
from websockets.protocol import State as WsState
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
        self.ws = None
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
            "&utterance_end_ms=2000"
        )
        headers = {"Authorization": f"Token {self.api_key}"}

        self.ws = await websockets.connect(
            DEEPGRAM_WS_URL + params,
            additional_headers=headers,
            ping_interval=20,
        )
        self._receive_task = asyncio.create_task(self._receive_loop(label))
        logger.info(f"Deepgram connected [{label}]")

    async def send_audio(self, audio_bytes: bytes):
        """Send an audio chunk to Deepgram."""
        if self.ws and self.ws.state == WsState.OPEN:
            await self.ws.send(audio_bytes)

    async def _receive_loop(self, label: str):
        """Receive and process responses from Deepgram with auto-reconnect."""
        max_retries = 5
        retry_delay = 1.0
        logger.info(f"Deepgram receive loop started [{label}]")

        msg_count = 0
        for attempt in range(max_retries):
            try:
                async for msg in self.ws:
                    data = json.loads(msg)
                    msg_count += 1

                    # Log first few messages and then periodically
                    if msg_count <= 5 or msg_count % 50 == 0:
                        msg_type = data.get("type", "Results")
                        is_final = data.get("is_final", "")
                        speech_final = data.get("speech_final", "")
                        alternatives = data.get("channel", {}).get("alternatives", [])
                        alt = alternatives[0] if alternatives else {}
                        text = alt.get("transcript", "")[:60]
                        logger.info(f"[{label}] msg#{msg_count} type={msg_type} final={is_final} speech_final={speech_final} text='{text}'")

                    # Final transcript of a complete phrase
                    if data.get("is_final") and data.get("speech_final"):
                        alternatives = data.get("channel", {}).get("alternatives", [])
                        alt = alternatives[0] if alternatives else {}
                        transcript = alt.get("transcript", "")
                        if transcript.strip():
                            logger.info(f"[{label}] transcript: {transcript}")
                            await self.on_transcript(label, 0, transcript)
                        else:
                            logger.debug(f"[{label}] empty speech_final, skipping")

                    # Utterance end — long pause in speech
                    if data.get("type") == "UtteranceEnd":
                        logger.info(f"[{label}] utterance_end")
                        await self.on_utterance_end(label)

                # Clean exit
                break

            except asyncio.CancelledError:
                break
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Deepgram WebSocket closed [{label}]: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Reconnecting [{label}] in {retry_delay}s (attempt {attempt + 1})...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 10.0)
                    try:
                        await self.connect(label)
                    except Exception:
                        continue
                break
            except Exception as e:
                logger.error(f"Deepgram receive error [{label}]: {e}")
                break

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
