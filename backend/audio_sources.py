"""
Источники звука v2.

- MicSource — микрофон (sounddevice), 16 кГц mono int16, чанки по 100 мс.
- TapSource — системный звук через Core Audio tap (утилита audiotee): всё, что играет на Mac,
  в том числе голос преподавателя из Zoom. Не нужен BlackHole и Multi-Output.
  Разрешение: «Запись системного звука» для приложения, из которого запущен ассистент
  (Terminal или Notes Helper.app — имя приходит в AXEL_HOST_APP).
  Без разрешения tap отдаёт нули — это ловит проверка /audio/test.
- BlackHoleSource — старый путь через виртуальное устройство (если tap не подошёл).

Каждый источник складывает байты PCM в asyncio.Queue и считает уровень сигнала.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

RATE = 16000
CHUNK = 1600  # 100 мс
AUDIOTEE_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "bin" / "audiotee",
    Path.home() / ".axel-assistant" / "bin" / "audiotee",
]


# Приложение, от имени которого macOS спрашивает разрешения (Electron-сборка передаёт своё имя).
HOST_APP = os.environ.get("AXEL_HOST_APP") or "Terminal"


def find_audiotee() -> Optional[str]:
    for p in AUDIOTEE_CANDIDATES:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which("audiotee")


def _db(chunk: bytes) -> float:
    if not chunk:
        return -90.0
    a = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
    if a.size == 0:
        return -90.0
    rms = math.sqrt(float(np.mean(a * a))) / 32768.0
    return 20 * math.log10(rms) if rms > 1e-6 else -90.0


class _Base:
    kind = "base"

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=400)
        self.level_db = -90.0
        self.peak_db = -90.0
        self.last_voice_t = 0.0      # когда последний раз был заметный сигнал
        self.last_chunk_t = 0.0
        self.nonzero_seen = False
        self.running = False
        self.error = ""
        self.device_name = ""

    def _push(self, chunk: bytes):
        db = _db(chunk)
        self.level_db = db
        self.peak_db = max(self.peak_db - 1.5, db)
        now = time.time()
        self.last_chunk_t = now
        if db > -50:
            self.last_voice_t = now
        if not self.nonzero_seen and any(chunk):
            self.nonzero_seen = True
        try:
            self.queue.put_nowait(chunk)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(chunk)
            except Exception:
                pass

    def push_threadsafe(self, chunk: bytes):
        self.loop.call_soon_threadsafe(self._push, chunk)

    def status(self) -> dict:
        return {"kind": self.kind, "running": self.running, "error": self.error,
                "level_db": round(self.level_db, 1), "device": self.device_name,
                "signal": self.nonzero_seen, "stale": self.running and time.time() - self.last_chunk_t > 2.0}


class MicSource(_Base):
    kind = "mic"

    def __init__(self, loop, device: Optional[str] = None):
        super().__init__(loop)
        self.device_pref = device
        self.stream: Optional[sd.InputStream] = None
        self._native = RATE
        self.gate_until = 0.0  # эхо-гейт: пока звучит преподаватель, микрофон глушим

    def _pick_device(self) -> int:
        devs = sd.query_devices()
        if self.device_pref:
            for i, d in enumerate(devs):
                if self.device_pref.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                    return i
        default_in = sd.default.device[0]
        if default_in is not None and default_in >= 0 and devs[default_in]["max_input_channels"] > 0:
            return int(default_in)
        for i, d in enumerate(devs):
            if d["max_input_channels"] > 0 and "blackhole" not in d["name"].lower():
                return i
        raise RuntimeError("Не найден микрофон")

    def start(self):
        try:
            sd._terminate(); sd._initialize()   # подхватить устройства, подключённые после запуска
        except Exception:
            pass
        idx = self._pick_device()
        info = sd.query_devices(idx)
        self.device_name = info["name"]
        self._native = int(info["default_samplerate"])
        block = int(self._native * 0.1)

        def cb(indata, frames, t, status):
            a = indata[:, 0]
            if self._native != RATE:
                n = int(len(a) * RATE / self._native)
                a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a.astype(np.float32)).astype(np.int16)
            data = a.tobytes()
            if time.time() < self.gate_until:
                data = bytes(len(data))
            self.push_threadsafe(data)

        self.stream = sd.InputStream(device=idx, channels=1, samplerate=self._native, dtype="int16",
                                     blocksize=block, callback=cb)
        self.stream.start()
        self.running = True
        self.error = ""
        logger.info(f"Микрофон: [{idx}] {self.device_name} @ {self._native} Гц")

    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass
            self.stream = None


class TapSource(_Base):
    """Системный звук через audiotee (Core Audio process tap)."""
    kind = "tap"

    def __init__(self, loop):
        super().__init__(loop)
        self.bin = find_audiotee()
        self.proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.restarts = 0
        self.device_name = "Системный звук (Core Audio tap)"

    @property
    def available(self) -> bool:
        return self.bin is not None

    def start(self):
        if not self.bin:
            raise RuntimeError("audiotee не найден — запусти scripts/setup_v2.sh")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.running = True

    def _run(self):
        while not self._stop.is_set():
            try:
                self.proc = subprocess.Popen(
                    [self.bin, "--sample-rate", str(RATE), "--chunk-duration", "0.1"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
                threading.Thread(target=self._read_err, args=(self.proc,), daemon=True).start()
                buf = b""
                while not self._stop.is_set():
                    data = self.proc.stdout.read(CHUNK * 2)
                    if not data:
                        break
                    buf += data
                    while len(buf) >= CHUNK * 2:
                        self.push_threadsafe(buf[:CHUNK * 2])
                        buf = buf[CHUNK * 2:]
                code = self.proc.poll()
                if not self._stop.is_set():
                    self.restarts += 1
                    self.error = f"audiotee завершился (код {code}), перезапуск"
                    logger.warning(self.error)
                    time.sleep(1.0)
            except Exception as e:
                self.error = f"audiotee: {e}"
                logger.error(self.error)
                time.sleep(2.0)
        self.running = False

    def _read_err(self, proc):
        try:
            for line in proc.stderr:
                s = line.decode(errors="ignore").strip()
                if '"error"' in s or "rror" in s:
                    self.error = s[:200]
                    logger.warning(f"audiotee: {s[:200]}")
        except Exception:
            pass

    def restart(self):
        """Пересоздать tap (после смены устройства вывода или если звук «завис»)."""
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def stop(self):
        self._stop.set()
        self.running = False
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except Exception:
                self.proc.kill()


class BlackHoleSource(MicSource):
    kind = "blackhole"

    def __init__(self, loop):
        super().__init__(loop, device="BlackHole")

    def start(self):
        names = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
        if not any("blackhole" in n.lower() for n in names):
            raise RuntimeError("BlackHole не установлен")
        super().start()


async def tap_selftest(timeout: float = 4.0) -> dict:
    """Проверка разрешения: проигрываем короткий звук и смотрим, дошёл ли он до tap."""
    bin_ = find_audiotee()
    if not bin_:
        return {"ok": False, "reason": "no_binary", "message": "audiotee не найден"}
    proc = await asyncio.create_subprocess_exec(
        bin_, "--sample-rate", str(RATE), "--chunk-duration", "0.1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    sound = "/System/Library/Sounds/Glass.aiff"
    peak = 0
    got = 0
    try:
        await asyncio.sleep(0.6)
        player = await asyncio.create_subprocess_exec("afplay", "-v", "0.25", sound)
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                data = await asyncio.wait_for(proc.stdout.read(CHUNK * 2), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if not data:
                break
            got += len(data)
            a = np.frombuffer(data[: len(data) // 2 * 2], dtype=np.int16)
            if a.size:
                peak = max(peak, int(np.max(np.abs(a))))
            if peak > 200 and time.time() - t0 > 0.8:
                break
        try:
            await asyncio.wait_for(player.wait(), timeout=3)
        except asyncio.TimeoutError:
            player.kill()
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                proc.kill()
    if got == 0:
        return {"ok": False, "reason": "no_data", "message": "audiotee не отдаёт данные"}
    if peak <= 200:
        return {"ok": False, "reason": "silence",
                "message": f"Звук системы не слышен: дай разрешение «Запись системного звука» приложению {HOST_APP} "
                           "(Настройки → Конфиденциальность → Запись экрана и системного звука), затем перезапусти ассистента."}
    return {"ok": True, "peak": peak, "message": "Системный звук слышен"}


class NullSource(_Base):
    """Тестовый «системный» источник: шлёт тишину, как настоящий tap; звук подаётся через /debug/inject."""
    kind = "test"

    def __init__(self, loop):
        super().__init__(loop)
        self.inject_until = 0.0
        self._task = None

    def start(self):
        self.running = True
        self.device_name = "Тестовый источник"

        async def silence():
            while self.running:
                if time.time() > self.inject_until:
                    self._push(bytes(CHUNK * 2))
                await asyncio.sleep(0.1)
        self._task = self.loop.create_task(silence())

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()


def default_output_device() -> str:
    """Имя текущего устройства вывода по умолчанию (для перезапуска tap при смене наушников/колонок)."""
    try:
        out = subprocess.run(["system_profiler", "SPAudioDataType", "-json"], capture_output=True, timeout=5).stdout
        import json as _json
        for grp in _json.loads(out).get("SPAudioDataType", []):
            for it in grp.get("_items", []):
                if it.get("coreaudio_default_audio_output_device") == "spaudio_yes":
                    return it.get("_name", "")
    except Exception:
        pass
    return ""
