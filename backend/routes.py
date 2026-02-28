"""
FastAPI app with SSE streaming and HTTP control endpoints.

SSE events:
- transcript: real-time transcription
- question_detected: interviewer asked a question
- ai_answer_start / ai_answer_chunk / ai_answer_end: streaming AI answer
- status: recording state, errors
- ping: keepalive
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
import asyncio
import json

app = FastAPI(title="Interview Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# SSE event queue (single consumer for MVP — one Electron client)
sse_queue: asyncio.Queue = asyncio.Queue()


async def emit_event(event: str, data: dict):
    """Push an event to all connected SSE clients."""
    await sse_queue.put({
        "event": event,
        "data": json.dumps(data, ensure_ascii=False),
    })


@app.get("/stream")
async def stream(request: Request):
    """SSE stream for the Electron overlay."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(sse_queue.get(), timeout=30)
                yield event
            except asyncio.TimeoutError:
                # Keepalive ping
                yield {"event": "ping", "data": ""}

    return EventSourceResponse(event_generator())


@app.get("/health")
async def health():
    return {"status": "ok"}
