FROM python:3.11-slim

WORKDIR /app

# ffmpeg: audio decoding for faster-whisper. espeak/libespeak1: TTS engine pyttsx3 needs on Linux
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak libespeak1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]