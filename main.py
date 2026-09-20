"""
Coach backend — text/audio in, fitness answer out (spoken).

Run locally (Windows/Mac/Linux with Python installed):
    pip install -r requirements.txt
    ollama pull llama3.2:3b
    python -m uvicorn main:app --reload --port 8000

Endpoints:
    GET  /health              -> {"status": "ok"}
    POST /ask       {"text"}  -> {"answer","muscles","equipment","audio_url"}
    POST /ask_audio  file     -> same, but transcribes the uploaded audio first
    GET  /audio/{file}        -> serves generated speech (wav)
"""

import os
import re
import uuid
import json
import logging
from pathlib import Path

import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coach")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.getenv("OLLAMA_MODEL", "coach-slm")
FALLBACK_MODEL = os.getenv("OLLAMA_FALLBACK_MODEL", "llama3.2:3b")
AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "generated_audio"))
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
MAX_AUDIO_FILES = 200

app = FastAPI(title="Coach Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SYSTEM_PROMPT = """You are Coach, a knowledgeable fitness and nutrition assistant. \
You help with: exercises and form, workout/training plans, which muscles a move \
targets, equipment use, general nutrition and diet guidance (calories, macros, \
meal ideas, pre/post-workout eating), and general fitness knowledge (recovery, \
sleep, hydration, injury-prevention basics, beginner guidance).

Answer in this strict JSON shape and nothing else:
{
  "answer": "<spoken-style coaching answer, 1-4 sentences>",
  "muscles": ["<primary muscle groups targeted, or empty list if not exercise-specific>"],
  "equipment": ["<equipment used, or empty list if not applicable>"],
  "meals": [{"meal": "<Breakfast/Lunch/Dinner/Snack>", "items": "<what to eat, brief>", "calories": "<approx kcal, e.g. '~450 kcal'>"}]
}
For nutrition/diet or general fitness questions, leave "muscles" and "equipment" empty \
unless a specific exercise is also discussed. When asked to build, plan, or suggest a \
day's or week's worth of meals or a diet plan, fill "meals" with each meal as a separate \
entry (Breakfast, Lunch, Dinner, and Snacks as relevant) — otherwise leave "meals" empty. \
Keep nutrition advice general and safe — no extreme calorie targets, no medical claims; \
suggest a doctor or dietitian for medical conditions, allergies, or eating disorders. \
Only answer fitness, training, nutrition, or general health/wellness questions. If asked \
something unrelated, politely redirect to fitness in the "answer" field with empty lists.
"""


class AskRequest(BaseModel):
    text: str


def _cleanup_old_audio():
    files = sorted(AUDIO_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    while len(files) > MAX_AUDIO_FILES:
        files.pop(0).unlink(missing_ok=True)


def call_ollama(user_text: str) -> dict:
    prompt = f"{SYSTEM_PROMPT}\nUser: {user_text}\nJSON:"

    def _generate(model: str) -> str:
        r = requests.post(OLLAMA_URL, json={"model": model, "prompt": prompt, "stream": False}, timeout=60)
        r.raise_for_status()
        return r.json().get("response", "").strip()

    try:
        raw = _generate(MODEL_NAME)
    except requests.exceptions.RequestException as e:
        log.warning("Model '%s' unavailable (%s) — using '%s'", MODEL_NAME, e, FALLBACK_MODEL)
        try:
            raw = _generate(FALLBACK_MODEL)
        except requests.exceptions.RequestException as e2:
            log.error("Ollama unreachable: %s", e2)
            raise HTTPException(status_code=503, detail="Ollama is not reachable. Is it running?")

    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Model returned non-JSON: %s", raw[:200])
        data = {"answer": raw or "Could you rephrase that?", "muscles": [], "equipment": []}

    data.setdefault("answer", "")
    data.setdefault("muscles", [])
    data.setdefault("equipment", [])
    data.setdefault("meals", [])
    return data


def synthesize_speech(text: str) -> str:
    """Offline TTS via pyttsx3. Returns filename, or '' if TTS isn't usable here."""
    if not text:
        return ""
    try:
        import pyttsx3
        _cleanup_old_audio()
        filename = f"{uuid.uuid4().hex}.wav"
        engine = pyttsx3.init()
        # pyttsx3's default voice name can mismatch what's actually installed
        # (e.g. "gmw/en" not found on this system), which raises instead of
        # falling back. Explicitly select the first available voice instead.
        voices = engine.getProperty("voices")
        if voices:
            engine.setProperty("voice", voices[0].id)
        engine.save_to_file(text, str(AUDIO_DIR / filename))
        engine.runAndWait()
        engine.stop()
        return filename
    except Exception as e:
        # Don't fail the whole request if TTS isn't available — frontend falls
        # back to the browser's own speechSynthesis when audio_url is null.
        log.warning("TTS unavailable (%s) — frontend will use browser speech instead", e)
        return ""


def transcribe_audio(file_path: str) -> str:
    from faster_whisper import WhisperModel
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(file_path)
    return " ".join(seg.text for seg in segments).strip()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(req: AskRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    result = call_ollama(req.text)
    audio_file = synthesize_speech(result["answer"])
    result["audio_url"] = f"/audio/{audio_file}" if audio_file else None
    return result


@app.post("/ask_audio")
async def ask_audio(audio: UploadFile = File(...)):
    tmp_path = Path(f"/tmp/{uuid.uuid4().hex}_{audio.filename}")
    try:
        tmp_path.write_bytes(await audio.read())
        text = transcribe_audio(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    if not text:
        raise HTTPException(status_code=422, detail="Could not transcribe audio")

    result = call_ollama(text)
    result["transcript"] = text
    audio_file = synthesize_speech(result["answer"])
    result["audio_url"] = f"/audio/{audio_file}" if audio_file else None
    return result


@app.get("/audio/{filename}")
def get_audio(filename: str):
    if not re.fullmatch(r"[0-9a-f]{32}\.wav", filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = AUDIO_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type="audio/wav")