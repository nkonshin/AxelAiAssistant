"""
OpenAI GPT-4o streaming wrapper with vision support.

Two modes:
- gpt-4o-mini: fast answers for simple questions (<1s TTFT)
- gpt-4o: code tasks, complex technical questions, screenshot analysis
"""

import os
from openai import AsyncOpenAI
from typing import AsyncGenerator, Optional


class LLMClient:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.system_prompt = self._build_system_prompt()

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

    async def generate_answer(
        self,
        question: str,
        context_history: list[dict],
        model: str = "gpt-4o-mini",
        screenshot_b64: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream answer chunks from OpenAI."""
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
            model = "gpt-4o"  # Vision requires gpt-4o
        else:
            messages.append({"role": "user",
                             "content": f"Вопрос интервьюера: {question}"})

        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=2048,
            temperature=0.3,
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
