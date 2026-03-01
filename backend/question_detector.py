"""
Detects when the interviewer asks a question from the transcript stream.

v2: Accumulates all speech from system audio until a real pause (2s),
then sends the entire block to LLM. This handles compound questions
and prevents false triggers on mid-sentence pauses.

Trigger mechanisms:
1. Pause-based: 2s of silence after system audio speech → auto-generate
2. Manual: force_trigger via hotkey (Cmd+Shift+A) → immediate generation
"""

import asyncio
import logging
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# How long to wait after last speech before auto-triggering (seconds)
PAUSE_TRIGGER_DELAY = 2.0


class QuestionDetector:
    def __init__(self, on_question_detected: Callable):
        self.on_question_detected = on_question_detected
        self.buffer: list[dict] = []
        self.last_source: Optional[str] = None
        self._debounce_task: Optional[asyncio.Task] = None

    async def add_transcript(self, source: str, speaker: int, text: str):
        """Add a recognized phrase to the buffer."""
        self.buffer.append({
            "source": source,
            "speaker": speaker,
            "text": text,
            "timestamp": time.time(),
        })
        self.last_source = source

        # If system audio is still speaking, reset the debounce timer
        if source == "system":
            self._reset_debounce()

    async def on_utterance_end(self, source: str):
        """Called on speech pause (utterance_end from Deepgram)."""
        if source == "system" and self._has_system_speech():
            # Start debounce timer — will trigger after PAUSE_TRIGGER_DELAY
            self._reset_debounce()

    def _has_system_speech(self) -> bool:
        """Check if buffer contains any system (interviewer) speech."""
        return any(p["source"] == "system" for p in self.buffer)

    def _reset_debounce(self):
        """Reset the debounce timer. Trigger fires after PAUSE_TRIGGER_DELAY of silence."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._debounce_wait())

    async def _debounce_wait(self):
        """Wait for pause, then trigger if still no new speech."""
        try:
            await asyncio.sleep(PAUSE_TRIGGER_DELAY)
            # Timer expired without being reset → real pause → trigger
            await self._trigger()
        except asyncio.CancelledError:
            # New speech arrived, timer was reset — do nothing
            pass

    async def _trigger(self):
        """Send accumulated system speech to LLM."""
        if not self.buffer:
            return

        full_text = " ".join(
            p["text"] for p in self.buffer if p["source"] == "system"
        )
        if not full_text.strip():
            return

        logger.info(f"Question detected: {full_text[:100]}...")
        self.buffer.clear()
        await self.on_question_detected(full_text)

    async def force_trigger(self):
        """Manual trigger via hotkey — uses all buffered text (both sources)."""
        # Cancel any pending debounce
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        if not self.buffer:
            return
        full_text = " ".join(p["text"] for p in self.buffer)
        if full_text.strip():
            logger.info(f"Force trigger: {full_text[:100]}...")
            self.buffer.clear()
            await self.on_question_detected(full_text)
