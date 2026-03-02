"""
Auto-trigger for AI answer generation based on speech pauses.

Accumulates all speech (both sources) and triggers LLM generation
after a configurable silence period. Sends full context (interviewer +
user speech) so the LLM understands the conversation.

Trigger mechanisms:
1. Pause-based: 2s of silence after speech → auto-generate
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
        self.mic_only_mode = False  # Set to True when BlackHole is unavailable

    async def add_transcript(self, source: str, speaker: int, text: str):
        """Add a recognized phrase to the buffer."""
        self.buffer.append({
            "source": source,
            "speaker": speaker,
            "text": text,
            "timestamp": time.time(),
        })
        self.last_source = source
        logger.debug(f"Buffer += [{source}] {text}")

        # Any speech resets the debounce timer
        trigger_source = source == "system" or (self.mic_only_mode and source == "mic")
        if trigger_source:
            self._reset_debounce()

    async def on_utterance_end(self, source: str):
        """Called on speech pause (utterance_end from Deepgram)."""
        trigger_source = source == "system" or (self.mic_only_mode and source == "mic")
        if trigger_source and self.buffer:
            self._reset_debounce()

    def _reset_debounce(self):
        """Reset the debounce timer. Trigger fires after PAUSE_TRIGGER_DELAY of silence."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._debounce_wait())

    async def _debounce_wait(self):
        """Wait for pause, then trigger if still no new speech."""
        try:
            await asyncio.sleep(PAUSE_TRIGGER_DELAY)
            await self._trigger()
        except asyncio.CancelledError:
            pass

    async def _trigger(self):
        """Send accumulated speech to LLM for answer generation."""
        if not self.buffer:
            return

        # Build text with source labels for LLM context
        parts = []
        for p in self.buffer:
            label = "Интервьюер" if p["source"] == "system" else "Кандидат"
            if self.mic_only_mode:
                # In mic-only mode, no source distinction
                parts.append(p["text"])
            else:
                parts.append(f"[{label}]: {p['text']}")

        full_text = " ".join(parts) if self.mic_only_mode else "\n".join(parts)

        if not full_text.strip():
            return

        logger.info(f"Auto-trigger: {full_text[:120]}...")
        self.buffer.clear()
        await self.on_question_detected(full_text)

    async def force_trigger(self):
        """Manual trigger via hotkey — uses all buffered text."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        if not self.buffer:
            return

        full_text = " ".join(p["text"] for p in self.buffer)
        if full_text.strip():
            logger.info(f"Force trigger: {full_text[:120]}...")
            self.buffer.clear()
            await self.on_question_detected(full_text)
