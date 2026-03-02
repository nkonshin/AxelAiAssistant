"""
Entry point: wires all modules together and starts FastAPI server.

Pipeline:
  AudioCapture -> DeepgramTranscriber -> QuestionDetector -> LLMClient -> SSE -> Electron
"""

import asyncio
import base64
import os
import uuid
import logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from config import (
    OPENAI_API_KEY, DEEPGRAM_API_KEY,
    LLM_PROVIDER, LLM_MODEL, CLI_PROXY_URL, CLI_PROXY_API_KEY,
    OPENAI_MODELS, CLAUDE_MODELS, CLAUDE_MODEL_LABELS,
    BACKEND_HOST, BACKEND_PORT,
)
from audio_capture import AudioCapture
from transcription import DeepgramTranscriber
from question_detector import QuestionDetector
from llm_client import LLMClient
from screenshot import ScreenshotCapture
from context_manager import ContextManager
from file_parser import extract_text
from routes import sse_queue, emit_event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Validate API keys
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not set — OpenAI provider will not work")
if not DEEPGRAM_API_KEY:
    logger.error("DEEPGRAM_API_KEY not set — create .env file from .env.example")

# Module instances
audio = AudioCapture()
context = ContextManager()
llm = LLMClient(openai_api_key=OPENAI_API_KEY or "", cli_proxy_url=CLI_PROXY_URL, cli_proxy_api_key=CLI_PROXY_API_KEY)
llm.set_provider(LLM_PROVIDER, LLM_MODEL)
screenshot_capture = ScreenshotCapture()

# Track current generation for cancellation
_current_generation: asyncio.Task | None = None


async def on_transcript(source: str, speaker: int, text: str):
    """Callback when Deepgram produces a final transcript."""
    context.add_transcript_line(source, speaker, text)
    await emit_event("transcript", {"source": source, "speaker": speaker, "text": text})
    await question_detector.add_transcript(source, speaker, text)


async def on_utterance_end(source: str):
    """Callback on speech pause."""
    await question_detector.on_utterance_end(source)


async def _generate_answer(question: str, answer_id: str, screenshot_b64: str | None = None):
    """Run LLM generation and stream chunks via SSE."""
    full_answer = ""
    try:
        async for chunk in llm.generate_answer(
            question=question,
            context_history=context.get_recent_context()[:-1],
            screenshot_b64=screenshot_b64,
        ):
            full_answer += chunk
            context.update_answer(chunk)
            await emit_event("ai_answer_chunk", {"text": chunk, "id": answer_id})
    except asyncio.CancelledError:
        logger.info(f"Generation cancelled [{answer_id}]")
    except Exception as e:
        err_str = str(e)
        logger.error(f"LLM error ({llm.provider}/{llm.model}): {e}")
        # Provide user-friendly error messages
        if "AuthenticationError" in type(e).__name__ or "401" in err_str:
            msg = f"API ключ недействителен для {llm.provider}. Проверьте .env файл."
        elif "RateLimitError" in type(e).__name__ or "429" in err_str:
            msg = f"Лимит запросов {llm.provider} превышен. Подождите или смените модель."
        elif "insufficient_quota" in err_str:
            msg = f"Недостаточно средств на аккаунте {llm.provider}."
        elif "Connection" in type(e).__name__ or "connect" in err_str.lower():
            msg = f"Нет подключения к {llm.provider}. Проверьте интернет."
        else:
            msg = f"LLM ошибка ({llm.provider}): {err_str[:150]}"
        await emit_event("status", {"type": "error", "message": msg})

    await emit_event("ai_answer_end", {"full_answer": full_answer, "id": answer_id})


async def on_question_detected(question_text: str):
    """Callback when a question is detected — start answer generation."""
    global _current_generation

    # Cancel previous generation if still running
    if _current_generation and not _current_generation.done():
        _current_generation.cancel()

    answer_id = str(uuid.uuid4())[:8]
    context.add_question(question_text)
    await emit_event("question_detected", {"text": question_text})
    await emit_event("ai_answer_start", {"question": question_text, "id": answer_id})

    _current_generation = asyncio.create_task(
        _generate_answer(question_text, answer_id)
    )


question_detector = QuestionDetector(on_question_detected=on_question_detected)

# Deepgram transcribers (two: mic and system audio)
transcriber_system = DeepgramTranscriber(DEEPGRAM_API_KEY, on_transcript, on_utterance_end)
transcriber_mic = DeepgramTranscriber(DEEPGRAM_API_KEY, on_transcript, on_utterance_end)


async def audio_to_deepgram(queue, transcriber: DeepgramTranscriber, label: str = "?"):
    """Pump audio chunks from capture queue to Deepgram WebSocket."""
    chunk_count = 0
    while True:
        try:
            audio_bytes = await queue.async_q.get()
            chunk_count += 1
            if chunk_count <= 3 or chunk_count % 100 == 0:
                logger.info(f"Audio pump [{label}]: chunk #{chunk_count}, {len(audio_bytes)} bytes")
            await transcriber.send_audio(audio_bytes)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Audio pump error [{label}]: {e}")
            await asyncio.sleep(0.1)


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info(f"Backend starting on {BACKEND_HOST}:{BACKEND_PORT}")
    if not OPENAI_API_KEY or not DEEPGRAM_API_KEY:
        logger.warning("Missing API keys — some features will not work")
    try:
        devices = audio.list_input_devices()
        logger.info(f"Available audio devices: {[d['name'] for d in devices]}")
    except Exception as e:
        logger.warning(f"Could not list audio devices: {e}")
    yield
    # Shutdown
    if audio.is_recording:
        audio.stop()
        await transcriber_mic.close()
        if audio.has_system_audio:
            await transcriber_system.close()
    logger.info("Backend shut down")


# --- FastAPI app ---

app = FastAPI(title="Interview Assistant", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "ok"}


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
                yield {"event": "ping", "data": ""}

    return EventSourceResponse(event_generator())


@app.post("/start")
async def start_recording():
    """Start audio capture and transcription."""
    try:
        await audio.start()

        # Always connect mic transcriber
        await transcriber_mic.connect(label="mic")
        asyncio.create_task(audio_to_deepgram(audio.mic_queue, transcriber_mic, "mic"))

        # Connect system audio transcriber only if BlackHole is available
        if audio.has_system_audio:
            await transcriber_system.connect(label="system")
            asyncio.create_task(audio_to_deepgram(audio.system_queue, transcriber_system, "system"))
            question_detector.mic_only_mode = False
            mode = "mic + system"
        else:
            question_detector.mic_only_mode = True
            mode = "mic only (BlackHole not found)"

        await emit_event("status", {"type": "recording", "message": f"Recording: {mode}"})
        logger.info(f"Recording started: {mode}")
        return {"status": "started", "mode": mode}
    except Exception as e:
        await emit_event("status", {"type": "error", "message": str(e)})
        logger.error(f"Start error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/stop")
async def stop_recording():
    """Stop audio capture and transcription."""
    audio.stop()
    await transcriber_mic.close()
    if audio.has_system_audio:
        await transcriber_system.close()
    await emit_event("status", {"type": "stopped", "message": "Recording stopped"})
    logger.info("Recording stopped")
    return {"status": "stopped"}


@app.post("/screenshot")
async def take_screenshot():
    """Capture screen and analyze with Vision model."""
    global _current_generation

    try:
        logger.info("Capturing screenshot...")
        img_b64 = screenshot_capture.capture_full_screen()
        logger.info(f"Screenshot captured ({len(img_b64)} bytes base64)")
    except Exception as e:
        logger.error(f"Screenshot capture failed: {e}")
        await emit_event("status", {"type": "error", "message": f"Screenshot failed: {e}"})
        return {"status": "error", "message": str(e)}

    question = "Проанализируй скриншот и помоги решить задачу."
    if question_detector.buffer:
        question = " ".join(p["text"] for p in question_detector.buffer)
        question_detector.buffer.clear()

    if _current_generation and not _current_generation.done():
        _current_generation.cancel()

    answer_id = str(uuid.uuid4())[:8]
    context.add_question(question, source="screenshot")
    await emit_event("ai_answer_start", {"question": "Screenshot analysis", "id": answer_id})

    _current_generation = asyncio.create_task(
        _generate_answer(question, answer_id, screenshot_b64=img_b64)
    )
    return {"status": "ok"}


@app.post("/force-answer")
async def force_answer():
    """Force answer generation from current buffer."""
    await question_detector.force_trigger()
    return {"status": "triggered"}


@app.get("/transcript")
async def get_transcript():
    """Get full transcript log."""
    return {"transcript": context.full_transcript}


@app.get("/status")
async def get_status():
    """Get current application state."""
    return {
        "recording": audio.is_recording,
        "has_system_audio": audio.has_system_audio,
        "has_openai_key": bool(OPENAI_API_KEY),
        "has_deepgram_key": bool(DEEPGRAM_API_KEY),
        "exchanges_count": len(context.exchanges),
        "transcript_lines": len(context.full_transcript),
    }


@app.post("/ask")
async def ask_question(request: Request):
    """Submit a manual text question for AI to answer."""
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        return {"status": "error", "message": "Empty question"}
    await on_question_detected(question)
    return {"status": "ok"}


@app.get("/settings/llm")
async def get_llm_settings():
    """Get current LLM provider, model, and available options."""
    return {
        "provider": llm.provider,
        "model": llm.model,
        "available": {
            "openai": OPENAI_MODELS,
            "claude": CLAUDE_MODELS,
        },
        "claude_labels": CLAUDE_MODEL_LABELS,
    }


@app.post("/settings/llm")
async def set_llm_settings(request: Request):
    """Change LLM provider and/or model at runtime."""
    body = await request.json()
    provider = body.get("provider", llm.provider)
    model = body.get("model", llm.model)

    if provider not in ("openai", "claude"):
        return {"status": "error", "message": f"Unknown provider: {provider}"}

    available = OPENAI_MODELS if provider == "openai" else CLAUDE_MODELS
    if model not in available:
        return {"status": "error", "message": f"Unknown model: {model}"}

    # Warn if switching to OpenAI without a key
    if provider == "openai" and not OPENAI_API_KEY:
        await emit_event("status", {"type": "error", "message": "OPENAI_API_KEY not set in .env"})
        return {"status": "error", "message": "OPENAI_API_KEY not configured"}

    llm.set_provider(provider, model)
    return {"status": "ok", "provider": provider, "model": model}


# --- Profile & Job Description settings ---

BACKEND_DIR = os.path.dirname(__file__)


def _read_md_file(filename: str) -> str:
    path = os.path.join(BACKEND_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _write_md_file(filename: str, content: str):
    path = os.path.join(BACKEND_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


@app.get("/settings/profile")
async def get_profile():
    """Get current candidate profile."""
    return {"content": _read_md_file("profile.md")}


@app.post("/settings/profile")
async def set_profile(request: Request):
    """Update candidate profile and reload system prompt."""
    body = await request.json()
    content = body.get("content", "")
    _write_md_file("profile.md", content)
    llm.reload_system_prompt()
    return {"status": "ok"}


@app.get("/settings/job")
async def get_job():
    """Get current job description."""
    return {"content": _read_md_file("job_description.md")}


@app.post("/settings/job")
async def set_job(request: Request):
    """Update job description and reload system prompt."""
    body = await request.json()
    content = body.get("content", "")
    _write_md_file("job_description.md", content)
    llm.reload_system_prompt()
    return {"status": "ok"}


@app.post("/settings/profile/reset")
async def reset_profile():
    """Reset profile to example template."""
    content = _read_md_file("profile.example.md")
    _write_md_file("profile.md", content)
    llm.reload_system_prompt()
    return {"status": "ok", "content": content}


@app.post("/settings/job/process")
async def process_job(request: Request):
    """Process job description text through LLM, save structured result."""
    body = await request.json()
    raw = body.get("content", "").strip()
    if not raw:
        return {"status": "error", "message": "Empty content"}
    try:
        result = await llm.format_document(raw_text=raw, doc_type="job")
    except Exception as e:
        logger.error(f"Job processing failed: {e}")
        return {"status": "error", "message": str(e)}
    _write_md_file("job_description.md", result)
    llm.reload_system_prompt()
    return {"status": "ok", "content": result}


@app.post("/settings/job/reset")
async def reset_job():
    """Reset job description to example template."""
    content = _read_md_file("job_description.example.md")
    _write_md_file("job_description.md", content)
    llm.reload_system_prompt()
    return {"status": "ok", "content": content}


# --- File upload with LLM processing ---

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}


async def _process_upload(file: UploadFile, doc_type: str, md_filename: str):
    """Process an uploaded file: parse → LLM format → save .md."""
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        return {"status": "error", "message": f"Формат {ext} не поддерживается. Используйте PDF, DOC или DOCX."}

    file_bytes = await file.read()
    logger.info(f"Upload: {filename} ({len(file_bytes)} bytes)")

    try:
        if ext == ".pdf":
            # Send PDF directly to LLM as base64
            pdf_b64 = base64.b64encode(file_bytes).decode()
            result = await llm.format_document(pdf_b64=pdf_b64, doc_type=doc_type)
        else:
            # Extract text from DOC/DOCX locally, then send to LLM
            raw_text = extract_text(file_bytes, filename)
            result = await llm.format_document(raw_text=raw_text, doc_type=doc_type)
    except Exception as e:
        logger.error(f"Upload processing failed: {e}")
        return {"status": "error", "message": str(e)}

    _write_md_file(md_filename, result)
    llm.reload_system_prompt()
    return {"status": "ok", "content": result}


@app.post("/settings/profile/upload")
async def upload_profile(file: UploadFile = File(...)):
    """Upload resume file, process with LLM, save as profile.md."""
    return await _process_upload(file, "profile", "profile.md")


@app.post("/settings/job/upload")
async def upload_job(file: UploadFile = File(...)):
    """Upload job description file, process with LLM, save as job_description.md."""
    return await _process_upload(file, "job", "job_description.md")


if __name__ == "__main__":
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
