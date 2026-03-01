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

        # Add conversation history
        for exchange in context_history:
            messages.append({"role": "user",
                             "content": f"Вопрос интервьюера: {exchange['question']}"})
            if exchange.get("answer"):
                messages.append({"role": "assistant",
                                 "content": exchange["answer"]})

        # Current question
        if screenshot_b64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text",
                     "text": f"Вопрос интервьюера: {question}\n\nНа скриншоте — задача или код."},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{screenshot_b64}",
                        "detail": "high",
                    }},
                ],
            })
            use_model = self._get_vision_model()
        else:
            messages.append({"role": "user",
                             "content": f"Вопрос интервьюера: {question}"})

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
