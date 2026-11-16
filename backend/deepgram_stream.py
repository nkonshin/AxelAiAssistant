"""
Потоковое распознавание Deepgram Nova-3 (русский) для одного источника звука.

Отдаёт события:
- on_interim(source, text)                 — промежуточный текст (для экрана и сброса таймера)
- on_final(source, text, speech_final)     — окончательный кусок фразы
- on_utterance_end(source)                 — длинная пауза (≥1 с без слов)
- on_status(source, state, message)        — подключено / переподключение / ошибка

Сам переподключается при обрыве. Если звука нет — шлёт KeepAlive, чтобы Deepgram не закрыл сокет.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable, Optional

import websockets
from websockets.protocol import State as WsState

logger = logging.getLogger(__name__)

URL = ("wss://api.deepgram.com/v1/listen?model=nova-3&language=ru&encoding=linear16&sample_rate=16000"
       "&channels=1&punctuate=true&interim_results=true&endpointing=300&utterance_end_ms=1000&vad_events=true")


class DeepgramStream:
    def __init__(self, api_key: str, source: str, queue: asyncio.Queue,
                 on_interim: Callable[[str, str], Awaitable[None]],
                 on_final: Callable[[str, str, bool], Awaitable[None]],
                 on_utterance_end: Callable[[str], Awaitable[None]],
                 on_status: Callable[[str, str, str], Awaitable[None]]):
        self.api_key = api_key
        self.source = source
        self.queue = queue
        self.on_interim = on_interim
        self.on_final = on_final
        self.on_utterance_end = on_utterance_end
        self.on_status = on_status
        self.ws = None
        self._task: Optional[asyncio.Task] = None
        self._stop = False
        self.state = "idle"
        self.last_msg_t = 0.0
        self.finals = 0

    def start(self):
        self._stop = False
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stop = True
        if self.ws is not None:
            try:
                await self.ws.send(json.dumps({"type": "CloseStream"}))
                await self.ws.close()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self.state = "idle"

    async def _set(self, state: str, msg: str = ""):
        self.state = state
        try:
            await self.on_status(self.source, state, msg)
        except Exception:
            pass

    async def _run(self):
        delay = 1.0
        while not self._stop:
            try:
                await self._set("connecting")
                async with websockets.connect(URL, additional_headers={"Authorization": f"Token {self.api_key}"},
                                              ping_interval=20, open_timeout=8, max_size=2 ** 22) as ws:
                    self.ws = ws
                    await self._set("ok")
                    delay = 1.0
                    # выбросить накопившийся за время переподключения звук
                    while not self.queue.empty():
                        self.queue.get_nowait()
                    sender = asyncio.create_task(self._sender(ws))
                    try:
                        await self._receiver(ws)
                    finally:
                        sender.cancel()
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.InvalidStatus as e:
                code = getattr(getattr(e, "response", None), "status_code", 0)
                msg = {401: "ключ Deepgram не принят", 402: "на Deepgram закончились кредиты"}.get(code, f"ошибка {code}")
                logger.error(f"Deepgram [{self.source}]: {msg}")
                await self._set("error", msg)
                if code in (401, 402, 403):
                    return
            except Exception as e:
                logger.warning(f"Deepgram [{self.source}] обрыв: {e}")
                await self._set("reconnecting", str(e)[:120])
            finally:
                self.ws = None
            if self._stop:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, 8.0)

    async def _sender(self, ws):
        last_send = time.time()
        while True:
            try:
                chunk = await asyncio.wait_for(self.queue.get(), timeout=3.0)
                await ws.send(chunk)
                last_send = time.time()
            except asyncio.TimeoutError:
                if ws.state == WsState.OPEN and time.time() - last_send > 3:
                    await ws.send(json.dumps({"type": "KeepAlive"}))
                    last_send = time.time()

    async def _receiver(self, ws):
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            self.last_msg_t = time.time()
            data = json.loads(raw)
            t = data.get("type", "Results")
            if t == "Results":
                alt = (data.get("channel", {}).get("alternatives") or [{}])[0]
                text = (alt.get("transcript") or "").strip()
                if data.get("is_final"):
                    if text:
                        self.finals += 1
                        await self.on_final(self.source, text, bool(data.get("speech_final")))
                    elif data.get("speech_final"):
                        await self.on_final(self.source, "", True)
                elif text:
                    await self.on_interim(self.source, text)
            elif t == "UtteranceEnd":
                await self.on_utterance_end(self.source)
