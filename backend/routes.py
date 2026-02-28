"""
FastAPI SSE streaming and shared utilities.

SSE events:
- transcript: real-time transcription
- question_detected: interviewer asked a question
- ai_answer_start / ai_answer_chunk / ai_answer_end: streaming AI answer
- status: recording state, errors
- ping: keepalive
"""

import asyncio
import json

# SSE event queue (single consumer for MVP — one Electron client)
sse_queue: asyncio.Queue = asyncio.Queue()


async def emit_event(event: str, data: dict):
    """Push an event to all connected SSE clients."""
    await sse_queue.put({
        "event": event,
        "data": json.dumps(data, ensure_ascii=False),
    })
