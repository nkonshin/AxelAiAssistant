"""
Conversation history and sliding context window for LLM.

Stores all exchanges locally but only sends the last N to the LLM
to stay within token limits.
"""

from dataclasses import dataclass, field
import time


@dataclass
class Exchange:
    question: str
    answer: str = ""
    candidate_said: str = ""  # What the candidate actually said (from mic transcript)
    timestamp: float = field(default_factory=time.time)
    source: str = "audio"  # "audio" or "screenshot"


class ContextManager:
    def __init__(self, max_recent: int = 5):
        self.exchanges: list[Exchange] = []
        self.max_recent = max_recent
        self.full_transcript: list[dict] = []
        self._mic_buffer: list[str] = []  # Candidate speech between questions

    def add_question(self, question: str, source: str = "audio") -> Exchange:
        """Start a new exchange with a detected question."""
        # Save accumulated mic speech to the previous exchange
        if self.exchanges and self._mic_buffer:
            self.exchanges[-1].candidate_said = " ".join(self._mic_buffer)
            self._mic_buffer.clear()

        exchange = Exchange(question=question, source=source)
        self.exchanges.append(exchange)
        return exchange

    def update_answer(self, answer_chunk: str):
        """Append a chunk to the current answer being generated."""
        if self.exchanges:
            self.exchanges[-1].answer += answer_chunk

    def get_recent_context(self) -> list[dict]:
        """Get the last N exchanges for LLM context, including what candidate said."""
        recent = self.exchanges[-self.max_recent:]
        result = []
        for e in recent:
            entry = {"question": e.question, "answer": e.answer}
            if e.candidate_said:
                entry["candidate_said"] = e.candidate_said
            result.append(entry)
        return result

    def get_last_answer(self) -> str:
        """Get the most recent complete answer."""
        if self.exchanges and self.exchanges[-1].answer:
            return self.exchanges[-1].answer
        return ""

    def add_transcript_line(self, source: str, speaker: int, text: str):
        """Append a transcript line to the full log."""
        self.full_transcript.append({
            "source": source,
            "speaker": speaker,
            "text": text,
            "timestamp": time.time(),
        })
        # Accumulate mic speech for context
        if source == "mic" and text.strip():
            self._mic_buffer.append(text.strip())
