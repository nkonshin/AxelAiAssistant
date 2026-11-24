"""
Кто говорит и когда отвечать.

Реплика преподавателя (системный звук) копится, пока студент не заговорит. Ответ запускаем,
когда преподаватель замолчал:
- speech_final от Deepgram + окно тишины (0,7 с, если фраза кончается на «?», иначе 1,1 с);
- UtteranceEnd (≥1 с без слов) — сразу;
- любой новый промежуточный текст преподавателя сбрасывает таймер, а если ответ уже пишется —
  после паузы ответ перегенерируется по всей реплике (вопрос оказался длиннее).
Короткие реплики без вопроса («так», «угу», «хорошо») не запускают ответ.
Режим «только вопросы» (по умолчанию): рассуждения преподавателя вслух без вопроса или просьбы
не запускают ответ — только реплики с «?», вопросительным словом в начале фразы или просьбой
(«расскажите», «покажите», «объясните»…).
Продолжение той же реплики после уже запущенного ответа помечается continuation=True: app решает,
заменить свежий ответ на месте или дать короткое «Дополнение» отдельной карточкой.
Ручной запуск (хоткей) работает всегда.

Если системного звука нет (режим «один микрофон»), весь текст идёт из микрофона, и автозапуск
срабатывает только на явных вопросах; основной путь — хоткей.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

FILLERS = {"так", "угу", "ага", "да", "хорошо", "понятно", "ясно", "ладно", "окей", "ок", "ну", "так так",
           "давайте", "отлично", "супер", "спасибо", "здравствуйте", "добрый день", "слышно", "меня слышно",
           "понял", "поняла", "интересно", "ну хорошо", "да да", "ага ага", "угу угу", "ну да", "так хорошо"}
QUESTION_WORDS = ("как", "что", "почему", "зачем", "какой", "какая", "какие", "каким", "какую", "каков", "чем",
                  "сколько", "где", "когда", "откуда", "объясни", "расскаж", "покаж", "опиши", "назови",
                  "можете", "можешь", "а если", "в чём", "в чем", "что такое", "зачем", "почему")


def _norm(t: str) -> str:
    return re.sub(r"[^\w\s]", "", t.lower()).strip()


def looks_like_question(text: str) -> bool:
    t = text.lower()
    if "?" in t:
        return True
    words = _norm(t)
    return any(re.search(rf"(^|\s){re.escape(w)}", words) for w in QUESTION_WORDS)


LEAD_WORDS = {"а", "ну", "так", "и", "вот", "хорошо", "ладно", "давайте", "окей", "ок", "да", "угу", "ага", "но",
              "тогда", "смотрите", "слушайте"}
INTERROG = {"как", "почему", "зачем", "какой", "какая", "какое", "какие", "каким", "какую", "каков", "какова", "каковы",
            "сколько", "где", "когда", "откуда", "куда", "чем", "что", "кто", "чего", "чему", "можете", "можешь"}
REQUEST_STEMS = ("расскаж", "покаж", "объясн", "поясн", "опиши", "опишите", "назов", "приведи", "приведите", "открой",
                 "прокрут", "докаж", "обоснуй", "сравни", "сравните", "уточни", "уточните", "продемонстр", "скажите",
                 "скажи ")


def is_request(text: str) -> bool:
    """Вопрос или просьба к студенту (а не рассуждение вслух)."""
    t = text.strip()
    if not t:
        return False
    if "?" in t:
        return True
    low = " " + t.lower()
    if any(re.search(r"[\s,.(«]" + re.escape(r), low) for r in REQUEST_STEMS):
        return True
    for sent in re.split(r"[.!…;:]+", t):
        w = re.findall(r"[а-яёa-z0-9]+", sent.lower())
        while w and w[0] in LEAD_WORDS:
            w = w[1:]
        if len(w) >= 3 and w[0] in INTERROG:
            return True
    return False


def is_filler(text: str) -> bool:
    n = _norm(text)
    if not n:
        return True
    if n in FILLERS:
        return True
    words = n.split()
    return len(words) <= 2 and "?" not in text and not looks_like_question(text)


@dataclass
class Line:
    who: str          # «Преподаватель» | «Я» | «Речь»
    text: str
    t: float = field(default_factory=time.time)


class TurnManager:
    def __init__(self, on_trigger: Callable[[str, str], Awaitable[None]],
                 on_event: Callable[[str, dict], Awaitable[None]]):
        self.on_trigger = on_trigger          # (текст вопроса, причина)
        self.on_event = on_event              # события для UI
        self.lines: list[Line] = []
        self.teacher_turn: list[str] = []
        self.turn_closed = True
        self.last_triggered = ""
        self.generating_for = ""
        self._timer: Optional[asyncio.Task] = None
        self.auto = True
        self.auto_mode = "questions"          # questions | all
        self.turn_id = 0                      # растёт с каждой новой репликой преподавателя
        self.last_trigger_turn = -1
        self.mic_only = False
        self.teacher_label = "Преподаватель"

    # ---------- служебное ----------

    def dialogue(self, n: int = 12) -> list[dict]:
        return [{"who": l.who, "text": l.text} for l in self.lines[-n:]]

    def _cancel_timer(self):
        if self._timer and not self._timer.done():
            self._timer.cancel()
        self._timer = None

    def _schedule(self, delay: float, reason: str):
        self._cancel_timer()

        async def fire():
            try:
                await asyncio.sleep(delay)
                await self._fire(reason)
            except asyncio.CancelledError:
                pass
        self._timer = asyncio.create_task(fire())

    def current_question(self) -> str:
        return " ".join(self.teacher_turn).strip()

    async def _fire(self, reason: str):
        q = self.current_question()
        if not q or q == self.last_triggered:
            return
        if not self.auto and reason != "manual":
            return
        continuation = self.last_trigger_turn == self.turn_id and bool(self.last_triggered)
        added = q[len(self.last_triggered):].strip() if continuation and q.startswith(self.last_triggered) else q
        if reason != "manual":
            if is_filler(q) or (continuation and is_filler(added)):
                logger.info(f"Пропуск (не вопрос): {q!r}")
                return
            if self.mic_only and not looks_like_question(q):
                return
            if self.auto_mode == "questions" and not is_request(added if continuation else q):
                logger.info(f"Пропуск (рассуждение, не вопрос): {(added if continuation else q)[:120]!r}")
                await self.on_event("skipped", {"text": (added if continuation else q)[:200]})
                return
        self.last_triggered = q
        self.last_trigger_turn = self.turn_id
        await self.on_trigger(q, reason, continuation=continuation, added=added)

    # ---------- события распознавания ----------

    async def interim(self, source: str, text: str):
        who = self._who(source)
        await self.on_event("interim", {"who": who, "source": source, "text": text})
        if self._is_teacher(source) and text:
            # преподаватель продолжает говорить — ждём конца
            self._cancel_timer()

    async def final(self, source: str, text: str, speech_final: bool):
        if text:
            who = self._who(source)
            if source == "mic" and not self.mic_only and self._echo_of_teacher(text):
                logger.info(f"Эхо преподавателя в микрофоне — пропуск: {text!r}")
                return
            self.lines.append(Line(who, text))
            self.lines = self.lines[-80:]
            await self.on_event("line", {"who": who, "source": source, "text": text})
            if self._is_teacher(source):
                if self.turn_closed:
                    self.teacher_turn = []
                    self.turn_closed = False
                    self.turn_id += 1
                self.teacher_turn.append(text)
            elif not is_filler(text):
                # студент заговорил по делу — следующая речь преподавателя будет новой репликой
                self.turn_closed = True
        if self._is_teacher(source) and self.teacher_turn:
            q = self.current_question()
            if speech_final:
                self._schedule(0.7 if q.rstrip().endswith("?") else 1.1, "pause")
            else:
                self._schedule(1.8, "pause-long")

    async def utterance_end(self, source: str):
        if self._is_teacher(source) and self.teacher_turn:
            self._cancel_timer()
            await self._fire("utterance_end")

    async def manual(self, text: str = "") -> bool:
        """Хоткей / кнопка / ручной ввод."""
        self._cancel_timer()
        if text.strip():
            q = text.strip()
            self.lines.append(Line("Вопрос (вручную)", q))
            self.last_triggered = q
            await self.on_trigger(q, "typed")
            return True
        q = self.current_question()
        if not q:
            recent = [l.text for l in self.lines[-6:] if l.who in (self.teacher_label, "Речь")]
            q = " ".join(recent[-2:]).strip()
        if not q:
            mine = [l.text for l in self.lines[-3:]]
            q = " ".join(mine).strip()
        if not q:
            return False
        self.last_triggered = q
        await self.on_trigger(q, "manual")
        return True

    # ---------- кто есть кто ----------

    def _is_teacher(self, source: str) -> bool:
        return source in ("tap", "blackhole", "system") or (self.mic_only and source == "mic")

    def _who(self, source: str) -> str:
        if self.mic_only:
            return "Речь"
        return self.teacher_label if self._is_teacher(source) else "Я"

    def _echo_of_teacher(self, text: str) -> bool:
        n = _norm(text)
        if len(n) < 6:
            return False
        now = time.time()
        for l in reversed(self.lines[-6:]):
            if l.who != self.teacher_label or now - l.t > 8:
                continue
            ln = _norm(l.text)
            if n in ln or difflib.SequenceMatcher(None, n, ln).ratio() > 0.6:
                return True
        return False

    def reset(self):
        self._cancel_timer()
        self.lines.clear()
        self.teacher_turn = []
        self.turn_closed = True
        self.last_triggered = ""
