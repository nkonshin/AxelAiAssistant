"""
Движок ответов v2: быстрые подсказки по контексту (шпаргалки, ноутбуки, резюме).

Провайдеры:
- anthropic — Claude через официальный SDK (Haiku 5.5 по умолчанию, Sonnet 5.5 — «умнее»).
  Контекст кладётся во второй блок system с cache_control (TTL 1 час) и прогревается
  запросом max_tokens=0, поэтому первый токен приходит быстро даже на 50–60 тыс. токенов контекста.
- openai — запасной вариант (gpt-4.1-mini): если ключа Anthropic нет или Claude недоступен.

Каждый запрос одноходовый: в user-сообщении — последние реплики разговора и текущий вопрос,
поэтому кэш system-префикса никогда не сбивается историей.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

import anthropic
from openai import AsyncOpenAI

from cc_engine import CC_MODELS, ClaudeCodePool

logger = logging.getLogger(__name__)

ANTHROPIC_MODELS = {
    "claude-haiku-5-5": "Claude Haiku 5.5 — быстрый",
    "claude-sonnet-5-5": "Claude Sonnet 5.5 — умнее, чуть медленнее",
}
OPENAI_MODELS = {
    "gpt-4.1-mini": "GPT-4.1 mini — запасной, быстрый",
    "gpt-4.1": "GPT-4.1 — запасной, умнее",
}
MAX_ANSWER_TOKENS = 700

STUDY_RULES = """Ты — суфлёр студента на устной онлайн-защите лабораторных работ. Студент — Никита; работы (ноутбуки и выводы) ниже, он делал их сам и сейчас показывает ноутбук преподавателю через демонстрацию экрана. Преподаватель задаёт вопросы голосом, ты видишь автоматическую расшифровку речи и должен мгновенно подсказать, что сказать.

ФОРМАТ ОТВЕТА — строго так:
**Скажи:** 1–3 коротких разговорных предложения от первого лица, которые можно сразу произнести вслух. Главное — в первом предложении. Конкретные числа и названия из работы — если к месту. Не больше 50 слов.
**Если уточнят:**
- 2–4 коротких пункта: факты, цифры, определения, раздел ноутбука и номер ячейки («5.2, In [18]»), которые помогут развить ответ.

ПРАВИЛА:
- Русский язык, живая устная речь студента: без канцелярита, без вступлений («Отличный вопрос», «Конечно»), без упоминания ИИ и подсказок.
- Опирайся на материалы ниже: шпаргалку и ноутбук. Числа и названия бери только оттуда, не выдумывай. Если в материалах ответа нет — дай короткий честный ответ по общей теории и добавь пункт «(в работе этого нет — сказать честно)».
- Вопрос про конкретный график, код или ячейку — назови раздел ноутбука (номер заголовка, как в скрипте защиты: «5.2») и ячейку In [n], и что в ней видно.
- Расшифровка речи бывает с ошибками («Boosting», «бустинк», «тьюки», «рандом форест», «силуэт», «эр квадрат»). Восстанавливай смысл по контексту работы.
- Преподаватель просит что-то показать — первым предложением скажи, какую ячейку открыть, например: «Покажу раздел 6.1, ячейку In [25] — там ручной ввод». Номера разделов — ровно как заголовки в ноутбуке.
- Если реплика — не вопрос (комментарий, «так, хорошо», «понятно», «продолжайте»), ответь одной строкой: что делать дальше по скрипту защиты (например, «Дальше: раздел 6 „Улучшение модели“ — ячейки In [21]–[24]»).
- Если вопрос с подвохом или про слабое место — признай ограничение спокойно и скажи, как это можно исправить.
- Краткость важнее полноты."""

INTERVIEW_RULES = """Ты — суфлёр кандидата на техническом собеседовании. Интервьюер задаёт вопросы голосом, ты видишь автоматическую расшифровку речи и должен мгновенно подсказать, что сказать. Профиль кандидата и вакансия — ниже.

ФОРМАТ ОТВЕТА — строго так:
**Скажи:** 1–3 коротких разговорных предложения от первого лица, которые можно сразу произнести вслух. Главное — в первом предложении. Не больше 50 слов.
**Если уточнят:**
- 2–4 коротких пункта: детали, примеры из опыта кандидата, термины.
Для задач на код — после этого минимальный рабочий фрагмент кода.

ПРАВИЛА:
- Русский язык (даже если вопрос на английском), живая устная речь, без вступлений и без упоминания ИИ.
- Опыт кандидата бери только из профиля, не выдумывай компаний, цифр и проектов.
- Расшифровка речи бывает с ошибками — восстанавливай смысл по контексту собеседования.
- Если реплика — не вопрос, ответь одной строкой «—».
- Краткость важнее полноты."""


@dataclass
class ContextBundle:
    """Что кладём в кэшируемый system-блок."""
    mode: str = "study"          # study | interview
    title: str = ""              # «2 Glass»
    text: str = ""               # шпаргалка + ноутбук + общая часть

    def rules(self) -> str:
        return STUDY_RULES if self.mode == "study" else INTERVIEW_RULES


@dataclass
class EngineState:
    provider: str = "anthropic"
    model: str = "claude-haiku-5-5"
    last_ttft: Optional[float] = None
    last_total: Optional[float] = None
    last_cache_read: int = 0
    last_input: int = 0
    warm: bool = False
    warm_error: str = ""
    notes: list[str] = field(default_factory=list)


class AnswerEngine:
    def __init__(self, anthropic_key: str | None, openai_key: str | None, cc_pool: ClaudeCodePool | None = None):
        self.anthropic_key = anthropic_key or ""
        self.openai_key = openai_key or ""
        self.cc = cc_pool
        self._claude: anthropic.AsyncAnthropic | None = None
        self._openai: AsyncOpenAI | None = None
        self._build_clients()
        self.ctx = ContextBundle()
        if self.anthropic_key:
            prov, model = "anthropic", "claude-haiku-5-5"
        elif self.cc and self.cc.available:
            prov, model = "claude-code", "cc-haiku"
        elif self.openai_key:
            prov, model = "openai", "gpt-4.1-mini"
        else:
            prov, model = "none", ""
        self.state = EngineState(provider=prov, model=model)
        # параметры «без размышлений» подбираются один раз: если модель отвергнет — упрощаем
        self._claude_extra: dict[str, dict] = {}

    # ---------- настройка ----------

    def _build_clients(self):
        self._claude = None
        self._openai = None
        if self.anthropic_key:
            self._claude = anthropic.AsyncAnthropic(
                api_key=self.anthropic_key,
                timeout=anthropic.Timeout(60.0, connect=5.0),
                max_retries=1,
            )
        if self.openai_key:
            self._openai = AsyncOpenAI(api_key=self.openai_key, timeout=60.0, max_retries=1)

    def set_keys(self, anthropic_key: str | None = None, openai_key: str | None = None):
        if anthropic_key is not None:
            self.anthropic_key = anthropic_key.strip()
        if openai_key is not None:
            self.openai_key = openai_key.strip()
        self._build_clients()
        self._claude_extra.clear()
        if self.anthropic_key and self.state.provider != "anthropic":
            self.state.provider, self.state.model = "anthropic", "claude-haiku-5-5"
        self.state.warm = False

    def set_model(self, model: str):
        if model in ANTHROPIC_MODELS:
            self.state.provider = "anthropic"
        elif model in CC_MODELS:
            self.state.provider = "claude-code"
        elif model in OPENAI_MODELS:
            self.state.provider = "openai"
        else:
            raise ValueError(f"Неизвестная модель: {model}")
        self.state.model = model
        self.state.warm = False

    def set_context(self, bundle: ContextBundle):
        self.ctx = bundle
        self.state.warm = False

    def available_models(self) -> list[dict]:
        out = []
        for m, (_alias, label) in CC_MODELS.items():
            out.append({"id": m, "label": label, "provider": "claude-code", "available": bool(self.cc and self.cc.available)})
        for m, label in ANTHROPIC_MODELS.items():
            out.append({"id": m, "label": label, "provider": "anthropic", "available": bool(self.anthropic_key)})
        for m, label in OPENAI_MODELS.items():
            out.append({"id": m, "label": label, "provider": "openai", "available": bool(self.openai_key)})
        return out

    # ---------- запрос ----------

    def _system_blocks(self) -> list[dict]:
        ctx_text = self.ctx.text.strip() or "(материалы не загружены)"
        header = f"МАТЕРИАЛЫ ({self.ctx.title}):\n\n" if self.ctx.title else "МАТЕРИАЛЫ:\n\n"
        return [
            {"type": "text", "text": self.ctx.rules()},
            {"type": "text", "text": header + ctx_text,
             "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        ]

    def _system_plain(self) -> str:
        return "\n\n".join(b["text"] for b in self._system_blocks())

    @staticmethod
    def build_user_text(question: str, dialogue: list[dict], previous_hint: str = "", note: str = "") -> str:
        lines = []
        if dialogue:
            lines.append("ХОД РАЗГОВОРА (последние реплики, расшифровка речи):")
            for d in dialogue:
                lines.append(f"{d['who']}: {d['text']}")
            lines.append("")
        if previous_hint:
            lines.append("ПРЕДЫДУЩАЯ ПОДСКАЗКА (уже показана студенту):")
            lines.append(previous_hint.strip()[:600])
            lines.append("")
        if note:
            lines.append(note)
            lines.append("")
        lines.append("ТЕКУЩАЯ РЕПЛИКА, на которую нужна подсказка:")
        lines.append(question.strip())
        return "\n".join(lines)

    def _claude_params(self, model: str) -> dict:
        if model in self._claude_extra:
            return self._claude_extra[model]
        if model.startswith("claude-haiku-5"):
            return {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}
        if model.startswith("claude-sonnet-5-5"):
            return {"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}}
        return {"output_config": {"effort": "low"}}

    def _claude_param_fallbacks(self, model: str) -> list[dict]:
        first = self._claude_params(model)
        chain = [first, {"output_config": {"effort": "low"}}, {}]
        uniq = []
        for p in chain:
            if p not in uniq:
                uniq.append(p)
        return uniq

    async def apply(self) -> dict:
        """Применить текущие материалы и модель: прогреть кэш / перезапустить процессы."""
        if self.cc and self.cc.available:
            cc_model = self.state.model if self.state.model in CC_MODELS else "cc-haiku"
            # пул подписки держим тёплым всегда: он же запасной вариант для API
            await self.cc.configure(self._system_plain(), cc_model)
        if self.state.provider == "anthropic":
            return await self.prewarm()
        self.state.warm = True
        return {"status": "ok", "provider": self.state.provider}

    async def prewarm(self) -> dict:
        """Записать контекст в кэш заранее (Claude), чтобы первый вопрос не ждал."""
        if self.state.provider != "anthropic" or not self._claude:
            self.state.warm = self.state.provider == "openai"
            return {"status": "skipped", "provider": self.state.provider}
        model = self.state.model
        t0 = time.perf_counter()
        last_err = None
        for extra in self._claude_param_fallbacks(model):
            try:
                resp = await self._claude.messages.create(
                    model=model,
                    max_tokens=0,
                    system=self._system_blocks(),
                    messages=[{"role": "user", "content": "Готов?"}],
                    **extra,
                )
                self._claude_extra[model] = extra
                u = resp.usage
                self.state.warm = True
                self.state.warm_error = ""
                info = {
                    "status": "ok", "seconds": round(time.perf_counter() - t0, 2),
                    "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
                    "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                    "params": extra,
                }
                logger.info(f"Prewarm {model}: {info}")
                return info
            except anthropic.BadRequestError as e:
                last_err = e
                logger.warning(f"Prewarm {model} with {extra} rejected: {e.message[:200]}")
                continue
            except Exception as e:
                last_err = e
                break
        self.state.warm = False
        self.state.warm_error = _human_error("anthropic", last_err)
        return {"status": "error", "message": self.state.warm_error}

    async def stream_answer(
        self,
        question: str,
        dialogue: list[dict],
        previous_hint: str = "",
        screenshot_b64: str | None = None,
        note: str = "",
    ) -> AsyncGenerator[str, None]:
        """Поток текста ответа. Если провайдер упал до первого токена — пробуем следующий."""
        user_text = self.build_user_text(question, dialogue, previous_hint, note)
        chain = [self.state.provider] + [p for p in ("claude-code", "anthropic", "openai") if p != self.state.provider]
        chain = [p for p in chain if self._provider_ready(p)]
        if not chain:
            raise RuntimeError("Нет рабочей модели: войди в Claude Code (claude /login) или вставь ключ Anthropic в настройках.")
        t0 = time.perf_counter()
        last_msg = ""
        for i, prov in enumerate(chain):
            got_first = False
            try:
                async for chunk in self._stream_provider(prov, user_text, screenshot_b64):
                    if not got_first:
                        got_first = True
                        self.state.last_ttft = time.perf_counter() - t0
                        if i > 0:
                            yield f"_({last_msg} — ответ через запасную модель)_\n\n"
                    yield chunk
                self.state.last_total = time.perf_counter() - t0
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_msg = _human_error(prov, e)
                logger.error(f"Провайдер {prov} упал: {e}")
                self.state.notes.append(last_msg)
                if got_first:
                    raise RuntimeError(last_msg) from e
        raise RuntimeError(last_msg or "все модели недоступны")

    def _provider_ready(self, prov: str) -> bool:
        if prov == "anthropic":
            return self._claude is not None
        if prov == "claude-code":
            return bool(self.cc and self.cc.available)
        if prov == "openai":
            return self._openai is not None
        return False

    async def _stream_provider(self, prov: str, user_text: str, screenshot_b64: str | None):
        if prov == "anthropic":
            async for ch in self._stream_claude(user_text, screenshot_b64):
                yield ch
        elif prov == "claude-code":
            async for ch in self.cc.stream(user_text, screenshot_b64):
                yield ch
        elif prov == "openai":
            model = self.state.model if self.state.model in OPENAI_MODELS else "gpt-4.1-mini"
            async for ch in self._stream_openai(model, user_text, screenshot_b64):
                yield ch

    async def _stream_claude(self, user_text: str, screenshot_b64: str | None):
        model = self.state.model
        content: list[dict] = []
        if screenshot_b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": screenshot_b64}})
        content.append({"type": "text", "text": user_text})

        last_err = None
        for extra in self._claude_param_fallbacks(model):
            try:
                async with self._claude.messages.stream(
                    model=model,
                    max_tokens=MAX_ANSWER_TOKENS,
                    system=self._system_blocks(),
                    messages=[{"role": "user", "content": content}],
                    **extra,
                ) as stream:
                    async for text in stream.text_stream:
                        yield text
                    final = await stream.get_final_message()
                self._claude_extra[model] = extra
                u = final.usage
                self.state.last_cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
                self.state.last_input = getattr(u, "input_tokens", 0) or 0
                if final.stop_reason == "refusal":
                    yield "\n\n_(модель отказалась отвечать — переформулируй вопрос текстом)_"
                return
            except anthropic.BadRequestError as e:
                # параметры «без размышлений» могли не подойти этой модели — пробуем проще
                last_err = e
                logger.warning(f"Claude {model} rejected params {extra}: {e.message[:200]}")
                continue
        raise last_err or RuntimeError("Claude: запрос отклонён")

    async def _stream_openai(self, model: str, user_text: str, screenshot_b64: str | None):
        if screenshot_b64:
            user_content = [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}", "detail": "high"}},
            ]
        else:
            user_content = user_text
        stream = await self._openai.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": self._system_plain()},
                      {"role": "user", "content": user_content}],
            max_completion_tokens=MAX_ANSWER_TOKENS,
            temperature=0.3,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def selftest(self) -> dict:
        """Короткий живой запрос: проверить ключ и замерить задержку."""
        t0 = time.perf_counter()
        text = ""
        try:
            async for ch in self.stream_answer("Проверка связи: ответь одним словом «работает».", [], note="Это технический тест, ответь одним словом."):
                text += ch
            return {"status": "ok", "provider": self.state.provider, "model": self.state.model,
                    "ttft": round(self.state.last_ttft or 0, 2), "total": round(time.perf_counter() - t0, 2),
                    "text": text.strip()[:80]}
        except Exception as e:
            return {"status": "error", "provider": self.state.provider, "message": str(e)[:200]}


def _human_error(provider: str, e: Exception | None) -> str:
    name = {"anthropic": "Claude API", "openai": "OpenAI", "claude-code": "Claude (подписка)"}.get(provider, provider)
    if e is None:
        return f"{name}: неизвестная ошибка"
    if isinstance(e, anthropic.AuthenticationError):
        return f"{name}: ключ API не принят — проверь ключ в настройках"
    if isinstance(e, anthropic.PermissionDeniedError):
        return f"{name}: у ключа нет доступа к модели"
    if isinstance(e, anthropic.NotFoundError):
        return f"{name}: модель не найдена"
    if isinstance(e, anthropic.RateLimitError):
        return f"{name}: лимит запросов или кредиты закончились"
    if isinstance(e, anthropic.APIConnectionError):
        return f"{name}: нет соединения с сервером"
    if isinstance(e, anthropic.APIStatusError):
        if e.status_code == 400 and "credit" in str(e).lower():
            return f"{name}: на балансе нет кредитов"
        return f"{name}: ошибка {e.status_code}"
    s = str(e)
    if "insufficient_quota" in s or "credit_balance" in s:
        return f"{name}: на балансе нет кредитов"
    return f"{name}: {s[:140]}"
