"""
LLM streaming wrapper with multi-provider support.

Providers:
- openai: OpenAI API (GPT-4o, GPT-4o-mini) via API key
- claude: Claude (Opus/Sonnet/Haiku) via CLIProxyAPI (Max subscription, OpenAI-compatible endpoint)
"""

import os
import logging
from openai import AsyncOpenAI
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, openai_api_key: str, cli_proxy_url: str, cli_proxy_api_key: str = "your-api-key-1"):
        # OpenAI client (direct API)
        self.openai_client = AsyncOpenAI(api_key=openai_api_key)

        # Claude client via CLIProxyAPI (OpenAI-compatible endpoint)
        self.claude_client = AsyncOpenAI(
            base_url=cli_proxy_url,
            api_key=cli_proxy_api_key,
        )

        # Runtime settings (changed via POST /settings)
        self.provider = "openai"  # "openai" or "claude"
        self.model = "gpt-4o-mini"

        self.system_prompt = self._build_system_prompt()
        self._mode = "interview"
        self._study_readme = ""
        self._study_explanation = ""

    def _get_client(self) -> AsyncOpenAI:
        """Return the active client based on current provider."""
        if self.provider == "claude":
            return self.claude_client
        return self.openai_client

    def set_provider(self, provider: str, model: str):
        """Switch LLM provider and model at runtime."""
        self.provider = provider
        self.model = model
        logger.info(f"LLM switched to {provider} / {model}")

    def set_study_context(self, readme: str, explanation: str):
        """Switch to study mode with lab context."""
        self._mode = "study"
        self._study_readme = readme
        self._study_explanation = explanation
        self.system_prompt = self._build_study_prompt(readme, explanation)
        logger.info("System prompt set to study mode")

    def set_interview_mode(self):
        """Switch back to interview mode."""
        self._mode = "interview"
        self.system_prompt = self._build_system_prompt()
        logger.info("System prompt set to interview mode")

    @staticmethod
    def _build_study_prompt(readme: str, explanation: str) -> str:
        return f"""Ты помогаешь студенту сдавать лабораторную работу дистанционно.
Преподаватель задаёт вопросы по теории и реализации кода.

ПРАВИЛА:
1. Отвечай КРАТКО и ПО СУЩЕСТВУ, на русском языке
2. Если вопрос про конкретную функцию или фрагмент кода — объясни что делает и почему так реализовано
3. Если вопрос по теории — дай чёткое определение и связь с кодом лабораторной
4. Не говори что ты AI-ассистент, отвечай от лица студента
5. Ответ должен звучать как устный ответ студента, а не как текст из учебника
6. Максимум 150-200 слов, если не задача по коду
7. Текст вопроса получен через автоматическую транскрипцию речи — он может содержать ошибки распознавания. Попробуй понять истинный смысл вопроса из контекста лабораторной работы

ЗАДАНИЕ ЛАБОРАТОРНОЙ:
{readme}

РАЗБОР ЛАБОРАТОРНОЙ (теория + код):
{explanation}"""

    def reload_system_prompt(self):
        """Rebuild system prompt after profile/job file update."""
        self.system_prompt = self._build_system_prompt()
        logger.info("System prompt reloaded")

    def _build_system_prompt(self) -> str:
        profile = self._load_file("profile.md",
                                  fallback="AI-инженер, 7+ лет опыта, Python/FastAPI/Docker/LLM")
        job_desc = self._load_file("job_description.md",
                                   fallback="[Не указано]")

        return f"""Ты — невидимый AI-ассистент на техническом собеседовании. Твоя задача — помочь кандидату ответить на вопрос интервьюера.

ПРАВИЛА:
1. Отвечай КРАТКО и ПО СУЩЕСТВУ — кандидат должен быстро прочитать и пересказать своими словами
2. Язык ответа: русский (если вопрос на английском — всё равно отвечай на русском)
3. Структура: сначала ключевой тезис (1-2 предложения), потом детали если нужно
4. Для кода: минимальный рабочий пример с комментариями
5. НЕ пиши преамбулы вроде "Вот ответ:" — сразу суть
6. Если вопрос про опыт — отвечай от первого лица как кандидат
7. Максимум 150-200 слов, если не задача по коду
8. Текст вопроса получен через автоматическую транскрипцию речи — он может содержать ошибки распознавания, искажённые или пропущенные слова. Попробуй понять истинный смысл вопроса из контекста технического собеседования, даже если отдельные слова выглядят бессмысленно

ПРОФИЛЬ КАНДИДАТА:
{profile}

ВАКАНСИЯ:
{job_desc}"""

    @staticmethod
    def _load_file(filename: str, fallback: str) -> str:
        path = os.path.join(os.path.dirname(__file__), filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return content if content else fallback
        except FileNotFoundError:
            return fallback

    PROFILE_PROMPT = (
        "Извлеки ключевую информацию из этого резюме/CV и оформи как структурированный "
        "markdown-профиль кандидата для использования на техническом собеседовании. "
        "Включи: имя, возраст (если есть), роль, годы опыта, ключевые навыки и технологии, "
        "основные проекты (кратко: что делал, стек, результат), образование, языки. "
        "Пиши на русском. Формат: заголовки ##, списки, без воды."
    )

    JOB_PROMPT = (
        "Извлеки ключевую информацию из этого описания вакансии и оформи как структурированный "
        "markdown для использования на техническом собеседовании. "
        "Включи: компания, позиция, ключевые требования, стек технологий, описание задач. "
        "Пиши на русском. Формат: заголовки ##, списки, без воды."
    )

    async def format_document(
        self,
        raw_text: str | None = None,
        pdf_b64: str | None = None,
        doc_type: str = "profile",
    ) -> str:
        """Process uploaded document through LLM and return structured markdown."""
        client = self._get_client()
        use_model = self.model
        prompt = self.PROFILE_PROMPT if doc_type == "profile" else self.JOB_PROMPT

        if pdf_b64:
            # Send PDF directly to the model as base64 document
            messages = [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "file", "file": {
                    "filename": "document.pdf",
                    "file_data": f"data:application/pdf;base64,{pdf_b64}",
                }},
            ]}]
            use_model = self._get_vision_model()
        else:
            messages = [{"role": "user", "content": f"{prompt}\n\n---\n\n{raw_text}"}]

        NO_TEMPERATURE_MODELS = {"gpt-5-mini", "gpt-5-nano"}
        params = dict(
            model=use_model,
            messages=messages,
            max_completion_tokens=2048,
            stream=False,
        )
        if use_model not in NO_TEMPERATURE_MODELS:
            params["temperature"] = 0.3

        response = await client.chat.completions.create(**params)
        return response.choices[0].message.content or ""

    def _get_vision_model(self) -> str:
        """Return the best vision-capable model for the current provider."""
        if self.provider == "claude":
            return "claude-sonnet-4-6"
        return "gpt-5-mini"

    async def generate_answer(
        self,
        question: str,
        context_history: list[dict],
        model: str | None = None,
        screenshot_b64: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream answer chunks from the active provider."""
        client = self._get_client()
        use_model = model or self.model

        messages = [{"role": "system", "content": self.system_prompt}]

        # Label depends on mode
        q_prefix = "Вопрос преподавателя:" if self._mode == "study" else "Вопрос интервьюера:"

        # Add conversation history (with what candidate actually said)
        for exchange in context_history:
            messages.append({"role": "user",
                             "content": f"{q_prefix} {exchange['question']}"})
            if exchange.get("answer"):
                answer_content = exchange["answer"]
                # Include what the candidate actually said for better context
                if exchange.get("candidate_said"):
                    answer_content += f"\n\n[Кандидат реально ответил: {exchange['candidate_said']}]"
                messages.append({"role": "assistant",
                                 "content": answer_content})

        # Current question
        if screenshot_b64:
            screenshot_hint = "На скриншоте — код или задача, которую обсуждают." if self._mode == "study" else "На скриншоте — задача или код."
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text",
                     "text": f"{q_prefix} {question}\n\n{screenshot_hint}"},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{screenshot_b64}",
                        "detail": "high",
                    }},
                ],
            })
            use_model = self._get_vision_model()
        else:
            messages.append({"role": "user",
                             "content": f"{q_prefix} {question}"})

        # GPT-5 mini/nano don't support custom temperature — only default (1)
        NO_TEMPERATURE_MODELS = {"gpt-5-mini", "gpt-5-nano"}

        params = dict(
            model=use_model,
            messages=messages,
            max_completion_tokens=2048,
            stream=True,
        )
        if use_model not in NO_TEMPERATURE_MODELS:
            params["temperature"] = 0.3

        stream = await client.chat.completions.create(**params)

        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
