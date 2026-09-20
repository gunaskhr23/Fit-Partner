# Coach — Voice Fitness SLM

## Local dev
```
cd backend
python -m pip install -r requirements.txt
ollama pull llama3.2:3b
uvicorn main:app --reload --port 8000
```
Open `index.html` in a browser (it calls `http://localhost:8000` by default).

## Deploy the backend
1. Copy `.env.example` to `.env` and fill in real values (set `ALLOWED_ORIGINS` to your deployed frontend's URL — don't leave it as `*` in production).
2. Build & run with Docker:
   ```
   docker build -t coach-backend .
   docker run -p 8000:8000 --env-file .env coach-backend
   ```
3. Deploy that container to any host that runs Docker + can reach an Ollama instance (Railway, Render, Fly.io, a VPS). Ollama itself needs to run alongside it (same host, or point `OLLAMA_URL` at a separate Ollama server).

## Deploy the frontend
- Open `index.html`, change `BACKEND_URL` at the top of the `<script>` to your deployed backend's public URL.
- Host it anywhere static (Netlify, Vercel, GitHub Pages) or publish it as a Claude artifact.

## Fine-tuning
Train a LoRA adapter on an instruction dataset of `{exercise, equipment, muscle_group, cues}`, merge or load it into Ollama via a `Modelfile`, and tag it `coach-slm` — the backend already looks for that model name first and falls back to the base model automatically.
