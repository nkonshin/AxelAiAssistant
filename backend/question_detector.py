"""
Detects when the interviewer asks a question from the transcript stream.

Three trigger mechanisms:
1. Content-based: phrase ends with "?" or starts with question words
2. Pause-based: utterance_end from system audio (1s silence)
3. Manual: force_trigger via hotkey (Cmd+Shift+A)

Includes debounce to prevent double-triggering.
"""

import time
from typing import Optional, Callable

QUESTION_STARTERS_RU = [
    "как ", "что ", "почему ", "зачем ", "какой ", "какая ", "какие ", "каким ",
    "можешь ", "можете ", "расскажи", "расскажите", "объясни", "объясните",
    "опиши", "опишите", "приведи", "приведите", "в чём ", "в чем ",
    "чем отличается", "какая разница", "что такое", "что значит",
    "когда ", "где ", "сколько ", "каков", "какова",
    # English fallback
    "how ", "what ", "why ", "can you", "could you", "tell me", "explain",
    "describe", "what is", "what are", "when ", "where ",
]

DEBOUNCE_SECONDS = 2.0


class QuestionDetector:
    def __init__(self, on_question_detected: Callable):
        self.on_question_detected = on_question_detected
        self.buffer: list[dict] = []
        self.last_source: Optional[str] = None
        self._last_trigger_time: float = 0

    async def add_transcript(self, source: str, speaker: int, text: str):
        """Add a recognized phrase to the buffer."""
        self.buffer.append({
            "source": source,
            "speaker": speaker,
            "text": text,
        })
        self.last_source = source

        # Immediate trigger if explicit question from interviewer
        if source == "system" and self._is_question(text):
            await self._trigger()

    async def on_utterance_end(self, source: str):
        """Called on speech pause (utterance_end from Deepgram)."""
        if source == "system" and self.buffer:
            system_phrases = [p for p in self.buffer if p["source"] == "system"]
            if system_phrases:
                await self._trigger()

    @staticmethod
    def _is_question(text: str) -> bool:
        """Check if text is a question by content."""
        text_lower = text.lower().strip()
        if text_lower.endswith("?"):
            return True
        for starter in QUESTION_STARTERS_RU:
            if text_lower.startswith(starter):
                return True
        return False

    async def _trigger(self):
        """Fire question detection with debounce guard."""
        now = time.time()
        if now - self._last_trigger_time < DEBOUNCE_SECONDS:
            return
        if not self.buffer:
            return

        full_text = " ".join(
            p["text"] for p in self.buffer if p["source"] == "system"
        )
        if not full_text.strip():
            return

        self._last_trigger_time = now
        self.buffer.clear()
        await self.on_question_detected(full_text)

    async def force_trigger(self):
        """Manual trigger via hotkey — uses all buffered text."""
        if not self.buffer:
            return
        full_text = " ".join(p["text"] for p in self.buffer)
        if full_text.strip():
            self.buffer.clear()
            self._last_trigger_time = time.time()
            await self.on_question_detected(full_text)
