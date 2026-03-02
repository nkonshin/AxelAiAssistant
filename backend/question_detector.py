"""
Auto-trigger for AI answer generation based on speech pauses.

System audio (interviewer) triggers auto-generation after silence.
Mic audio (candidate) is buffered separately — it does NOT auto-trigger,
but can be manually sent to LLM via F5 hotkey (POST /trigger-mic).

Trigger mechanisms:
1. Pause-based: 3s of silence after interviewer speech → auto-generate
2. Mic trigger: F5 hotkey → send candidate's mic buffer to LLM
3. Force trigger: Cmd+Shift+A → send everything (both buffers)
"""

import asyncio
import logging
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# How long to wait after last speech (from any source) before auto-triggering.
# 2s was too fast (triggered mid-question), 4s too slow. 3s is the sweet spot:
# just long enough to avoid mid-question triggers with Whisper's ~3s chunks.
PAUSE_TRIGGER_DELAY = 3.0


class QuestionDetector:
    def __init__(self, on_question_detected: Callable):
        self.on_question_detected = on_question_detected
        self.buffer: list[dict] = []      # System (interviewer) speech only
        self.mic_buffer: list[dict] = []   # Mic (candidate) speech — manual trigger only
        self.last_source: Optional[str] = None
        self._debounce_task: Optional[asyncio.Task] = None
        self.mic_only_mode = False  # Set to True when BlackHole is unavailable

    async def add_transcript(self, source: str, speaker: int, text: str):
        """Add a recognized phrase to the appropriate buffer."""
        entry = {
            "source": source,
            "speaker": speaker,
            "text": text,
            "timestamp": time.time(),
        }
        self.last_source = source

        if self.mic_only_mode:
            # No BlackHole — all audio goes to main buffer (old behavior)
            self.buffer.append(entry)
        elif source == "mic":
            # Mic speech → separate buffer, does NOT auto-trigger
            self.mic_buffer.append(entry)
            logger.debug(f"Mic buffer += {text}")
        else:
            # System (interviewer) speech → main buffer, auto-triggers
            self.buffer.append(entry)
            logger.debug(f"Buffer += [{source}] {text}")

        # Any speech from any source resets the debounce timer.
        # Mic speech delays auto-trigger (good: prevents firing while candidate speaks)
        # but doesn't add to the system buffer (so no echo-answers).
        self._reset_debounce()

    async def on_utterance_end(self, source: str):
        """Called on speech pause (utterance_end from VAD/Deepgram)."""
        if self.buffer:
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
        """Send accumulated system speech to LLM for answer generation."""
        if not self.buffer:
            return

        # Build text with source labels for LLM context
        parts = []
        for p in self.buffer:
            label = "Интервьюер" if p["source"] == "system" else "Кандидат"
            if self.mic_only_mode:
                parts.append(p["text"])
            else:
                parts.append(f"[{label}]: {p['text']}")

        full_text = " ".join(parts) if self.mic_only_mode else "\n".join(parts)

        if not full_text.strip():
            return

        logger.info(f"Auto-trigger: {full_text[:120]}...")
        self.buffer.clear()
        self.mic_buffer.clear()  # Clear mic context after answer generation
        await self.on_question_detected(full_text)

    async def trigger_with_mic(self):
        """Manual mic trigger via F5 — send candidate's mic buffer to LLM."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        if not self.mic_buffer:
            logger.info("Mic trigger: empty mic buffer, nothing to send")
            return

        full_text = " ".join(p["text"] for p in self.mic_buffer)
        if full_text.strip():
            logger.info(f"Mic trigger (F5): {full_text[:120]}...")
            self.mic_buffer.clear()
            self.buffer.clear()  # Also clear system buffer to avoid stale auto-trigger
            await self.on_question_detected(full_text)

    async def force_trigger(self):
        """Manual trigger via Cmd+Shift+A — uses ALL buffered text (both sources)."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        all_entries = self.buffer + self.mic_buffer
        if not all_entries:
            return

        full_text = " ".join(p["text"] for p in all_entries)
        if full_text.strip():
            logger.info(f"Force trigger: {full_text[:120]}...")
            self.buffer.clear()
            self.mic_buffer.clear()
            await self.on_question_detected(full_text)
