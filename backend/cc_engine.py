"""
Claude через Claude Code CLI (подписка Max, без отдельного ключа API).

Держим 2 постоянных процесса `claude -p --input-format stream-json`: системный промпт с
материалами загружается один раз и кэшируется, поэтому первый токен приходит за ~1 с.
Два процесса — чтобы новый вопрос не ждал, пока допишется ответ на предыдущий.
Каждый процесс перезапускается после N вопросов (чтобы история не разрасталась)
и при смене материалов (другая работа / режим).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

WORK_DIR = Path.home() / ".axel-assistant" / "cc-work"
MAX_QUESTIONS_PER_WORKER = 12
CC_MODELS = {
    "cc-haiku": ("haiku", "Claude Haiku (подписка) — быстрый"),
    "cc-sonnet": ("sonnet", "Claude Sonnet (подписка) — умнее"),
}


def find_claude() -> Optional[str]:
    for cand in (shutil.which("claude"), str(Path.home() / ".local/bin/claude"),
                 "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


class _Worker:
    def __init__(self, idx: int, claude_bin: str, model_alias: str, sys_file: Path):
        self.idx = idx
        self.bin = claude_bin
        self.model_alias = model_alias
        self.sys_file = sys_file
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.lock = asyncio.Lock()
        self.ready = asyncio.Event()
        self.questions = 0
        self.dead = False
        self.error = ""
        self._stderr_task: Optional[asyncio.Task] = None

    async def start(self):
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("CLAUDE_CODE") and k not in ("CLAUDECODE", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        args = [self.bin, "-p", "--model", self.model_alias,
                "--system-prompt-file", str(self.sys_file),
                "--setting-sources", "", "--strict-mcp-config", "--tools", "",
                "--no-session-persistence",
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--verbose", "--include-partial-messages"]
        if self.model_alias == "sonnet":
            args += ["--effort", "low"]
        self.proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(WORK_DIR), env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=2 ** 24)
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        # прогрев: первый короткий вопрос записывает материалы в кэш
        t0 = time.perf_counter()
        try:
            async for _ in self._ask_raw("Готов? Ответь одним словом."):
                pass
            self.ready.set()
            logger.info(f"CC worker {self.idx} ({self.model_alias}) готов за {time.perf_counter() - t0:.1f} с")
        except Exception as e:
            self.dead = True
            self.error = str(e)
            logger.error(f"CC worker {self.idx} не запустился: {e}")

    async def _drain_stderr(self):
        try:
            while self.proc and self.proc.stderr:
                line = await self.proc.stderr.readline()
                if not line:
                    break
                s = line.decode(errors="ignore").strip()
                if s and "no stdin data" not in s:
                    logger.warning(f"CC worker {self.idx} stderr: {s[:300]}")
                    self.error = s[:300]
        except Exception:
            pass

    async def _ask_raw(self, content) -> AsyncGenerator[str, None]:
        """Отправить сообщение и выдавать текстовые дельты до события result."""
        if not self.proc or self.proc.returncode is not None:
            self.dead = True
            raise RuntimeError("процесс Claude Code завершился")
        msg = {"type": "user", "message": {"role": "user", "content": content}}
        self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        await self.proc.stdin.drain()
        while True:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=90)
            if not line:
                self.dead = True
                raise RuntimeError(f"Claude Code закрыл поток. {self.error}")
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "stream_event":
                e = ev.get("event", {})
                if e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "text_delta":
                    yield e["delta"]["text"]
            elif t == "result":
                if ev.get("is_error"):
                    raise RuntimeError(str(ev.get("result") or ev.get("subtype") or "ошибка Claude Code")[:300])
                return

    async def ask(self, content, out: asyncio.Queue):
        """Выполнить вопрос, складывая дельты в очередь. Дочитывает поток даже если потребитель ушёл."""
        async with self.lock:
            self.questions += 1
            try:
                async for d in self._ask_raw(content):
                    out.put_nowait(("delta", d))
                out.put_nowait(("end", None))
            except Exception as e:
                out.put_nowait(("error", str(e)))

    @property
    def busy(self) -> bool:
        return self.lock.locked()

    async def stop(self):
        self.dead = True
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                self.proc.kill()
        if self._stderr_task:
            self._stderr_task.cancel()


class ClaudeCodePool:
    def __init__(self, size: int = 2):
        self.size = size
        self.bin = find_claude()
        self.model = "cc-haiku"
        self.system_text = ""
        self.workers: list[_Worker] = []
        self._gen = 0
        self._sys_dir = Path(tempfile.mkdtemp(prefix="axel-cc-"))
        self._restart_task: Optional[asyncio.Task] = None
        self.last_error = ""

    @property
    def available(self) -> bool:
        return self.bin is not None

    def status(self) -> dict:
        return {
            "available": self.available,
            "model": self.model,
            "ready": sum(1 for w in self.workers if w.ready.is_set() and not w.dead),
            "starting": sum(1 for w in self.workers if not w.ready.is_set() and not w.dead),
            "error": self.last_error,
        }

    async def configure(self, system_text: str, model: str | None = None):
        """Новые материалы или модель — перезапустить процессы в фоне."""
        if model:
            self.model = model
        self.system_text = system_text
        if not self.available:
            return
        if self._restart_task and not self._restart_task.done():
            self._restart_task.cancel()
        self._restart_task = asyncio.create_task(self._restart_all())

    async def _restart_all(self):
        self._gen += 1
        gen = self._gen
        sys_file = self._sys_dir / f"system_{gen}.txt"
        sys_file.write_text(self.system_text, encoding="utf-8")
        alias = CC_MODELS.get(self.model, ("haiku", ""))[0]
        old = self.workers
        new = [_Worker(i, self.bin, alias, sys_file) for i in range(self.size)]
        self.workers = new
        await asyncio.gather(*(w.start() for w in new))
        errs = [w.error for w in new if w.dead]
        self.last_error = errs[0] if errs and len(errs) == len(new) else ""
        for w in old:
            asyncio.create_task(w.stop())

    async def _refresh_worker(self, w: _Worker):
        """Заменить «уставший» процесс свежим, не трогая остальные."""
        if w not in self.workers:
            return
        nw = _Worker(w.idx, self.bin, w.model_alias, w.sys_file)
        await nw.start()
        if w in self.workers:
            self.workers[self.workers.index(w)] = nw
        async with w.lock:          # дождаться, пока старый процесс допишет ответ
            pass
        await w.stop()

    async def wait_ready(self, timeout: float = 30) -> bool:
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            if any(w.ready.is_set() and not w.dead for w in self.workers):
                return True
            if self.workers and all(w.dead for w in self.workers):
                return False
            await asyncio.sleep(0.1)
        return False

    async def stream(self, text: str, image_b64: str | None = None) -> AsyncGenerator[str, None]:
        if not self.available:
            raise RuntimeError("Claude Code не найден (нужна команда claude)")
        if not self.workers:
            await self.configure(self.system_text)
        if not await self.wait_ready():
            raise RuntimeError(f"Claude Code не готов: {self.last_error or 'проверь вход в аккаунт (claude /login)'}")
        # свободный готовый процесс; если все заняты — ждём первый освободившийся
        worker = None
        t0 = time.perf_counter()
        while worker is None:
            free = [w for w in self.workers if w.ready.is_set() and not w.dead and not w.busy]
            if free:
                worker = min(free, key=lambda w: w.questions)
            elif time.perf_counter() - t0 > 20:
                raise RuntimeError("Claude Code занят слишком долго")
            else:
                await asyncio.sleep(0.05)
        content: list | str = text
        if image_b64:
            content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                       {"type": "text", "text": text}]
        q: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(worker.ask(content, q))
        try:
            while True:
                kind, val = await q.get()
                if kind == "delta":
                    yield val
                elif kind == "end":
                    break
                else:
                    raise RuntimeError(val)
        finally:
            # процесс дочитает ответ сам; после лимита вопросов — заменим свежим
            if worker.dead and self.available:
                asyncio.create_task(self._refresh_worker(worker))
            elif worker.questions >= MAX_QUESTIONS_PER_WORKER:
                async def _later(w=worker, t=task):
                    try:
                        await t
                    except Exception:
                        pass
                    await self._refresh_worker(w)
                asyncio.create_task(_later())

    async def shutdown(self):
        for w in self.workers:
            await w.stop()
