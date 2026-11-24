"""
Axel v2 — суфлёр для онлайн-защиты лаб и собеседований.

Конвейер: системный звук (Core Audio tap) + микрофон → Deepgram Nova-3 (ru) →
TurnManager (кто говорит, когда вопрос закончился) → AnswerEngine (Claude) → SSE → окно.

Запуск: python app.py  (UI: http://127.0.0.1:8765/ui)
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home() / ".axel-assistant"
HOME.mkdir(parents=True, exist_ok=True)
ENV_FILE = ROOT / ".env"
SETTINGS_FILE = HOME / "settings.json"
SESSIONS_DIR = HOME / "sessions"
DEFAULT_PACK = Path.home() / "Documents/PSU/4.1/Анализ данных/Ассистент"

load_dotenv(HOME / ".env")
load_dotenv(ENV_FILE, override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(HOME / "v2.log", encoding="utf-8")])
logger = logging.getLogger("axel")

from answer_engine import AnswerEngine, ANTHROPIC_MODELS, OPENAI_MODELS  # noqa: E402
from audio_sources import (BlackHoleSource, MicSource, NullSource, TapSource, default_output_device,
                           find_audiotee, tap_selftest, HOST_APP)  # noqa: E402
from cc_engine import CC_MODELS, ClaudeCodePool  # noqa: E402
from context_pack import StudyPack, interview_bundle  # noqa: E402
from deepgram_stream import DeepgramStream  # noqa: E402
from turns import TurnManager  # noqa: E402

PORT = int(os.getenv("AXEL_PORT", "8765"))


# ---------------- настройки ----------------

def load_settings() -> dict:
    s = {"pack_folder": str(DEFAULT_PACK) if DEFAULT_PACK.exists() else "", "active_lab": 0,
         "mode": "study", "model": "", "system_source": "tap", "auto": True, "auto_mode": "questions", "font": 22, "mic_enabled": True}
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def save_settings():
    try:
        SETTINGS_FILE.write_text(json.dumps(S, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Не сохранил настройки: {e}")


def write_env_key(name: str, value: str):
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    lines = [l for l in lines if not l.startswith(f"{name}=")]
    lines.append(f"{name}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[name] = value


S = load_settings()


# ---------------- шина событий ----------------

class Bus:
    def __init__(self):
        self.clients: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.clients.add(q)
        return q

    def unsubscribe(self, q):
        self.clients.discard(q)

    async def emit(self, event: str, data: dict):
        msg = {"event": event, "data": json.dumps(data, ensure_ascii=False)}
        for q in list(self.clients):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass


bus = Bus()


# ---------------- состояние ----------------

class App:
    def __init__(self):
        self.cc = ClaudeCodePool(size=2)
        self.engine = AnswerEngine(os.getenv("ANTHROPIC_API_KEY"), os.getenv("OPENAI_API_KEY"), self.cc)
        self.pack = StudyPack()
        self.turns = TurnManager(self.on_trigger, bus.emit)
        self.listening = False
        self.mic: Optional[MicSource] = None
        self.sys: Optional[TapSource | BlackHoleSource] = None
        self.streams: list[DeepgramStream] = []
        self.stt_state: dict[str, str] = {}
        self.gen_task: Optional[asyncio.Task] = None
        self.gen_tasks: dict[str, asyncio.Task] = {}
        self.answers: list[dict] = []
        self.pending_shot: Optional[str] = None
        self.level_task: Optional[asyncio.Task] = None
        self.session_file: Optional[Path] = None
        self.tap_check: dict = {}
        self.deepgram_key = os.getenv("DEEPGRAM_API_KEY", "")

    # ----- материалы -----

    async def load_context(self):
        if S["mode"] == "interview":
            self.engine.set_context(interview_bundle())
        else:
            if S.get("pack_folder") and os.path.isdir(S["pack_folder"]):
                if self.pack.folder != S["pack_folder"]:
                    self.pack.load(S["pack_folder"])
                if self.pack.labs:
                    self.pack.active = min(max(int(S.get("active_lab", 0)), 0), len(self.pack.labs) - 1)
            self.engine.set_context(self.pack.bundle())
        if S.get("model"):
            try:
                self.engine.set_model(S["model"])
            except ValueError:
                pass
        await bus.emit("context", self.context_info())
        info = await self.engine.apply()
        await bus.emit("engine", self.engine_info(extra=info))

    def context_info(self) -> dict:
        return {"mode": S["mode"], "pack": self.pack.info(), "title": self.engine.ctx.title,
                "chars": len(self.engine.ctx.text)}

    def engine_info(self, extra: dict | None = None) -> dict:
        st = self.engine.state
        return {"provider": st.provider, "model": st.model, "ttft": st.last_ttft, "total": st.last_total,
                "warm": st.warm, "warm_error": st.warm_error, "cc": self.cc.status(),
                "has_anthropic_key": bool(self.engine.anthropic_key),
                "models": self.engine.available_models(), "extra": extra or {}}

    # ----- слушание -----

    async def start_listening(self):
        if self.listening:
            return
        loop = asyncio.get_running_loop()
        if not self.deepgram_key:
            await bus.emit("toast", {"level": "error", "text": "Нет ключа Deepgram в .env — распознавание не запустится"})
            return
        self.session_file = SESSIONS_DIR / f"{datetime.now():%Y-%m-%d_%H-%M}.md"
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.mic = None
        if S.get("mic_enabled", True) and os.getenv("AXEL_NO_MIC") != "1":
            self.mic = MicSource(loop)
            try:
                self.mic.start()
            except Exception as e:
                self.mic.error = str(e)
                await bus.emit("toast", {"level": "error", "text": f"Микрофон: {e}"})
        self.sys = None
        src = S.get("system_source", "tap")
        if src in ("tap", "blackhole", "test"):
            cand = {"tap": TapSource, "blackhole": BlackHoleSource, "test": NullSource}[src](loop)
            try:
                cand.start()
                self.sys = cand
            except Exception as e:
                await bus.emit("toast", {"level": "error", "text": f"Системный звук: {e}. Работаю только с микрофоном."})
        self.turns.mic_only = self.sys is None and self.mic is not None
        self.streams = []
        if self.sys:
            self.streams.append(self._make_stream("tap", self.sys.queue))
        if self.mic and self.mic.running:
            self.streams.append(self._make_stream("mic", self.mic.queue))
        for s in self.streams:
            s.start()
        self.listening = True
        self.level_task = asyncio.create_task(self._levels_loop())
        await bus.emit("listening", self.listen_info())
        logger.info(f"Слушаю: system={src if self.sys else 'нет'}, mic={self.mic.device_name if self.mic else 'выкл'}")

    def _make_stream(self, source: str, q: asyncio.Queue) -> DeepgramStream:
        return DeepgramStream(self.deepgram_key, source, q, self.turns.interim, self._on_final,
                              self.turns.utterance_end, self._on_stt_status)

    async def _on_final(self, source: str, text: str, speech_final: bool):
        if text and self.session_file:
            who = self.turns._who(source)
            self._log(f"**{who}:** {text}")
        await self.turns.final(source, text, speech_final)

    async def _on_stt_status(self, source: str, state: str, msg: str):
        self.stt_state[source] = state
        await bus.emit("stt", {"source": source, "state": state, "message": msg})
        if state == "error":
            await bus.emit("toast", {"level": "error", "text": f"Распознавание ({source}): {msg}"})

    async def stop_listening(self):
        self.listening = False
        if self.level_task:
            self.level_task.cancel()
        for s in self.streams:
            await s.stop()
        self.streams = []
        for src in (self.mic, self.sys):
            if src:
                src.stop()
        await bus.emit("listening", self.listen_info())

    def listen_info(self) -> dict:
        return {"listening": self.listening, "mic_only": self.turns.mic_only,
                "mic": self.mic.status() if self.mic else None,
                "system": self.sys.status() if self.sys else None,
                "system_source": S.get("system_source"), "stt": self.stt_state,
                "tap_available": find_audiotee() is not None, "tap_check": self.tap_check,
                "auto": self.turns.auto, "auto_mode": self.turns.auto_mode}

    async def _levels_loop(self):
        silent_since = time.time()
        warned = False
        last_dev_check = 0.0
        out_dev = await asyncio.to_thread(default_output_device)
        try:
            while self.listening:
                now = time.time()
                # сменилось устройство вывода (наушники/колонки) — пересоздать tap
                if self.sys and self.sys.kind == "tap" and now - last_dev_check > 4:
                    last_dev_check = now
                    dev = await asyncio.to_thread(default_output_device)
                    if dev and out_dev and dev != out_dev:
                        logger.info(f"Устройство вывода: {out_dev} → {dev}, перезапускаю tap")
                        self.sys.restart()
                        await bus.emit("toast", {"level": "info", "text": f"Звук теперь идёт в «{dev}» — перезапустил захват"})
                    if dev:
                        out_dev = dev
                # эхо-гейт: пока звучит системный звук, микрофон глушим (на случай колонок)
                if self.sys and self.mic and now - self.sys.last_voice_t < 0.15:
                    self.mic.gate_until = now + 0.35
                if self.sys and self.sys.nonzero_seen:
                    silent_since = now
                elif self.sys and now - silent_since > 25 and not warned:
                    warned = True
                    await bus.emit("toast", {"level": "warn", "text":
                        "Системный звук пока полностью пустой. Если в Zoom уже кто-то говорил — нет разрешения на запись "
                        "системного звука: нажми «Проверить звук» в настройках."})
                await bus.emit("levels", {
                    "mic": round(self.mic.level_db, 1) if self.mic else None,
                    "system": round(self.sys.level_db, 1) if self.sys else None,
                    "system_signal": bool(self.sys and self.sys.nonzero_seen),
                })
                await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            pass

    # ----- ответы -----

    # Ответ на экране не перезаписывается: если преподаватель продолжил ту же реплику, свежий ответ
    # (моложе REPLACE_WINDOW с) заменяется на месте, а более старый остаётся и ниже идёт «Дополнение».
    REPLACE_WINDOW = 1.5
    MAX_PARALLEL = 2

    async def on_trigger(self, question: str, reason: str, screenshot: str | None = None,
                         continuation: bool = False, added: str = ""):
        shot = screenshot or self.pending_shot
        self.pending_shot = None
        now = time.time()
        last = self.answers[-1] if self.answers else None
        kind, replaces, note = "answer", None, ""
        prev = next((a["answer"] for a in reversed(self.answers) if a.get("answer")), "")
        if continuation and last and last.get("status") in ("streaming", "done"):
            if now - last["t"] < self.REPLACE_WINDOW and last.get("status") == "streaming":
                replaces = last["id"]
                t = self.gen_tasks.get(last["id"])
                if t and not t.done():
                    t.cancel()
                last["status"] = "replaced"
            else:
                kind = "addon"
                prev = last.get("answer") or prev
                note = ("Преподаватель продолжил ту же реплику, а подсказка на неё уже на экране (ПРЕДЫДУЩАЯ ПОДСКАЗКА). "
                        f"Дай короткое ДОПОЛНЕНИЕ только к новой части: «{added[:400]}». "
                        "Формат тот же, но «Скажи:» — 1–2 предложения, «Если уточнят:» — 1–2 пункта; не повторяй уже сказанное.")
        # не держим больше MAX_PARALLEL генераций: самые старые останавливаем
        running = [(a_id, t) for a_id, t in self.gen_tasks.items() if not t.done()]
        while len(running) >= self.MAX_PARALLEL:
            a_id, t = running.pop(0)
            t.cancel()
        aid = uuid.uuid4().hex[:8]
        item = {"id": aid, "question": question, "reason": reason, "answer": "", "t": now,
                "shot": bool(shot), "status": "streaming", "kind": kind, "added": added if kind == "addon" else "",
                "replaces": replaces}
        self.answers.append(item)
        self.answers = self.answers[-50:]
        await bus.emit("answer_start", {k: item[k] for k in ("id", "question", "reason", "shot", "kind", "added", "replaces")})
        task = asyncio.create_task(self._generate(item, prev, shot, note))
        self.gen_tasks = {k: v for k, v in self.gen_tasks.items() if not v.done()}
        self.gen_tasks[aid] = task
        self.gen_task = task

    async def _generate(self, item: dict, prev: str, shot: str | None, extra_note: str = ""):
        t0 = time.perf_counter()
        first = None
        buf = ""
        last_flush = 0.0
        try:
            note = "К вопросу приложен скриншот экрана студента (то, что видит преподаватель)." if shot else ""
            if extra_note:
                note = (note + "\n" + extra_note).strip()
            async for ch in self.engine.stream_answer(item["question"], self.turns.dialogue(12), prev, shot, note):
                if first is None:
                    first = time.perf_counter() - t0
                item["answer"] += ch
                buf += ch
                now = time.perf_counter()
                if now - last_flush > 0.04 or len(buf) > 40:
                    await bus.emit("answer_delta", {"id": item["id"], "text": buf})
                    buf = ""
                    last_flush = now
            if buf:
                await bus.emit("answer_delta", {"id": item["id"], "text": buf})
            item["status"] = "done"
            st = self.engine.state
            await bus.emit("answer_end", {"id": item["id"], "ttft": round(first or 0, 2),
                                          "total": round(time.perf_counter() - t0, 2),
                                          "provider": st.provider, "model": st.model})
            tag = "Дополнение" if item.get("kind") == "addon" else "Вопрос"
            q = item.get("added") if item.get("kind") == "addon" else item["question"]
            self._log(f"> **{tag}:** {q}\n\n{item['answer']}\n")
        except asyncio.CancelledError:
            if item["status"] != "replaced":
                item["status"] = "stopped"
            if buf:
                await bus.emit("answer_delta", {"id": item["id"], "text": buf})
            await bus.emit("answer_end", {"id": item["id"], "replaced": True})
        except Exception as e:
            item["status"] = "error"
            logger.error(f"Ответ не получен: {e}")
            await bus.emit("answer_error", {"id": item["id"], "message": str(e)[:300]})

    def _log(self, text: str):
        if not self.session_file:
            self.session_file = SESSIONS_DIR / f"{datetime.now():%Y-%m-%d_%H-%M}.md"
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.session_file, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%H:%M:%S} {text}\n\n")
        except Exception:
            pass

    # ----- скриншот -----

    def capture_screen(self, display: int = 1) -> Optional[str]:
        path = Path(tempfile.gettempdir()) / f"axel_shot_{uuid.uuid4().hex[:6]}.jpg"
        try:
            subprocess.run(["screencapture", "-x", "-t", "jpg", "-D", str(display), str(path)],
                           timeout=8, check=True, capture_output=True)
            from PIL import Image
            img = Image.open(path)
            img.thumbnail((1600, 1600))
            out = io.BytesIO()
            img.convert("RGB").save(out, format="JPEG", quality=80)
            return base64.b64encode(out.getvalue()).decode()
        except Exception as e:
            logger.error(f"Скриншот не удался: {e}")
            return None
        finally:
            try:
                path.unlink()
            except Exception:
                pass


A = App()


# ---------------- HTTP ----------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Axel v2 стартует на 127.0.0.1:{PORT}")
    asyncio.create_task(_startup())
    yield
    try:
        await A.stop_listening()
    except Exception:
        pass
    await A.cc.shutdown()


async def _startup():
    A.turns.auto = S.get("auto", True) is not False
    A.turns.auto_mode = S.get("auto_mode", "questions") if S.get("auto_mode") in ("questions", "all") else "questions"
    try:
        await A.load_context()
    except Exception as e:
        logger.error(f"Контекст не загрузился: {e}")
        await bus.emit("toast", {"level": "error", "text": f"Материалы не загрузились: {e}"})
    if os.getenv("AXEL_AUTOLISTEN", "1") == "1":
        await asyncio.sleep(0.5)
        await A.start_listening()


app = FastAPI(title="Axel v2", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
STATIC = Path(__file__).resolve().parent / "static"


@app.get("/health")
async def health():
    return {"status": "ok", "version": 2}


@app.get("/ui")
async def ui():
    return FileResponse(STATIC / "ui.html", headers={"Cache-Control": "no-store"})


@app.get("/events")
async def events(request: Request):
    q = bus.subscribe()

    async def gen():
        try:
            yield {"event": "hello", "data": json.dumps(full_state(), ensure_ascii=False)}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    yield await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            bus.unsubscribe(q)
    return EventSourceResponse(gen())


def full_state() -> dict:
    return {"settings": S, "context": A.context_info(), "engine": A.engine_info(), "listen": A.listen_info(),
            "answers": A.answers[-10:], "lines": A.turns.dialogue(30), "deepgram": bool(A.deepgram_key)}


@app.get("/state")
async def state():
    return full_state()


@app.post("/listen/{action}")
async def listen(action: str):
    if action == "start":
        await A.start_listening()
    elif action == "stop":
        await A.stop_listening()
    elif action == "toggle":
        await (A.stop_listening() if A.listening else A.start_listening())
    elif action == "restart":
        await A.stop_listening()
        await asyncio.sleep(0.3)
        await A.start_listening()
    return A.listen_info()


@app.post("/ask")
async def ask(request: Request):
    body = await _json(request)
    ok = await A.turns.manual(body.get("text", ""))
    if not ok:
        await bus.emit("toast", {"level": "warn", "text": "Пока нечего отправлять: вопрос не услышан. Напиши его текстом."})
    return {"ok": ok}


@app.post("/cancel")
async def cancel():
    for t in list(A.gen_tasks.values()):
        if not t.done():
            t.cancel()
    return {"ok": True}


@app.post("/ui/jump")
async def ui_jump():
    """Хоткей ⌘⇧J: прокрутить ленту к самому новому ответу."""
    await bus.emit("jump", {})
    return {"ok": True}


@app.post("/screenshot")
async def screenshot(request: Request):
    body = await _json(request)
    display = int(body.get("display", S.get("shot_display", 1)))
    shot = await asyncio.to_thread(A.capture_screen, display)
    if not shot:
        await bus.emit("toast", {"level": "error", "text": f"Скриншот не получился: дай {HOST_APP} разрешение «Запись экрана»"})
        return {"ok": False}
    if body.get("mode", "ask") == "attach":
        A.pending_shot = shot
        await bus.emit("toast", {"level": "info", "text": "Скриншот приложится к следующему вопросу"})
        return {"ok": True}
    q = A.turns.current_question() or body.get("text") or \
        "Что сейчас на экране и что про это сказать преподавателю? Если там код или график — объясни коротко."
    await A.on_trigger(q, "screenshot", screenshot=shot)
    return {"ok": True}


@app.post("/lab")
async def set_lab(request: Request):
    body = await _json(request)
    idx = int(body.get("index", 0))
    if not (0 <= idx < len(A.pack.labs)):
        return JSONResponse({"ok": False, "message": "нет такой работы"}, status_code=400)
    S["active_lab"] = idx
    S["mode"] = "study"
    save_settings()
    A.pack.active = idx
    await A.load_context()
    await bus.emit("toast", {"level": "info", "text": f"Работа: {A.pack.labs[idx].name}"})
    return {"ok": True, **A.context_info()}


@app.post("/mode")
async def set_mode(request: Request):
    body = await _json(request)
    mode = body.get("mode", "study")
    if mode not in ("study", "interview"):
        return JSONResponse({"ok": False}, status_code=400)
    S["mode"] = mode
    save_settings()
    A.turns.teacher_label = "Преподаватель" if mode == "study" else "Интервьюер"
    await A.load_context()
    return {"ok": True, **A.context_info()}


@app.post("/model")
async def set_model(request: Request):
    body = await _json(request)
    try:
        A.engine.set_model(body.get("model", ""))
    except ValueError as e:
        return JSONResponse({"ok": False, "message": str(e)}, status_code=400)
    S["model"] = A.engine.state.model
    save_settings()
    info = await A.engine.apply()
    await bus.emit("engine", A.engine_info(extra=info))
    return {"ok": True, **A.engine_info(extra=info)}


@app.post("/keys")
async def set_keys(request: Request):
    body = await _json(request)
    if "anthropic" in body:
        key = body["anthropic"].strip()
        write_env_key("ANTHROPIC_API_KEY", key)
        A.engine.set_keys(anthropic_key=key)
        S["model"] = A.engine.state.model
        save_settings()
    if "deepgram" in body and body["deepgram"].strip():
        A.deepgram_key = body["deepgram"].strip()
        write_env_key("DEEPGRAM_API_KEY", A.deepgram_key)
    info = await A.engine.apply()
    test = await A.engine.selftest() if A.engine.anthropic_key else {}
    await bus.emit("engine", A.engine_info(extra={**info, "selftest": test}))
    return {"ok": True, "selftest": test, "prewarm": info}


@app.post("/selftest")
async def selftest():
    res = await A.engine.selftest()
    await bus.emit("engine", A.engine_info(extra={"selftest": res}))
    return res


@app.post("/pack")
async def set_pack(request: Request):
    body = await _json(request)
    folder = body.get("folder", "").strip("\r\n\t")
    if not os.path.isdir(folder):
        return JSONResponse({"ok": False, "message": "папка не найдена"}, status_code=400)
    S["pack_folder"] = folder
    S["active_lab"] = 0
    save_settings()
    A.pack = StudyPack()
    await A.load_context()
    return {"ok": True, **A.context_info()}


@app.post("/settings")
async def set_settings(request: Request):
    body = await _json(request)
    restart_audio = False
    for k in ("auto", "font", "shot_display", "auto_mode"):
        if k in body:
            S[k] = body[k]
    if "auto" in body:
        A.turns.auto = bool(body["auto"])
    if body.get("auto_mode") in ("questions", "all"):
        A.turns.auto_mode = body["auto_mode"]
    if "system_source" in body and body["system_source"] in ("tap", "blackhole", "none", "test"):
        S["system_source"] = body["system_source"]
        restart_audio = True
    if "mic_enabled" in body:
        S["mic_enabled"] = bool(body["mic_enabled"])
        restart_audio = True
    save_settings()
    if restart_audio and A.listening:
        await A.stop_listening()
        await asyncio.sleep(0.3)
        await A.start_listening()
    await bus.emit("settings", S)
    return {"ok": True, "settings": S}


@app.post("/audio/test")
async def audio_test():
    was = A.listening
    if was and A.sys and A.sys.kind == "tap":
        # во время прослушивания проверяем по живому потоку
        before = A.sys.nonzero_seen
        A.sys.nonzero_seen = False
        proc = await asyncio.create_subprocess_exec("afplay", "-v", "0.25", "/System/Library/Sounds/Glass.aiff")
        await asyncio.sleep(1.6)
        await proc.wait()
        ok = A.sys.nonzero_seen
        A.sys.nonzero_seen = ok or before
        res = {"ok": ok, "message": "Системный звук слышен" if ok else
               f"Системный звук не слышен: дай разрешение «Запись системного звука» для {HOST_APP} "
               "(Настройки → Конфиденциальность и безопасность → Запись экрана и системного звука), потом перезапусти ассистента."}
    else:
        res = await tap_selftest()
    A.tap_check = res
    await bus.emit("listening", A.listen_info())
    return res


@app.post("/open-privacy")
async def open_privacy():
    subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AudioCapture"])
    return {"ok": True}


@app.post("/reset")
async def reset():
    A.turns.reset()
    A.answers.clear()
    await bus.emit("reset", {})
    return {"ok": True}


@app.post("/debug/inject")
async def debug_inject(request: Request):
    """Тест без Zoom: подать WAV (16 кГц mono s16) в поток «преподавателя» как будто он говорит."""
    body = await _json(request)
    path = body.get("path", "")
    target = body.get("source", "tap")
    stream = next((s for s in A.streams if s.source == target), None)
    if not stream:
        return JSONResponse({"ok": False, "message": f"нет потока {target}"}, status_code=400)
    data = Path(path).read_bytes()
    if data[:4] == b"RIFF":
        data = data[44:]
    src = A.sys if target == "tap" else A.mic
    if src is not None and hasattr(src, "inject_until"):
        src.inject_until = time.time() + len(data) / 32000 + 0.3

    async def feed():
        for i in range(0, len(data), 3200):
            src._push(data[i:i + 3200]) if src else stream.queue.put_nowait(data[i:i + 3200])
            await asyncio.sleep(0.1)
    asyncio.create_task(feed())
    return {"ok": True, "seconds": round(len(data) / 32000, 1)}


async def _json(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
