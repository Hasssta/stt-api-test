"""API PhoWhisper (chạy CPU bằng faster-whisper int8).

  GET  /health       -> server còn sống không, model chạy trên thiết bị nào
  POST /transcribe   -> gửi 1 file audio (WAV, FLAC, OGG, MP3), nhận lại chữ

Chạy: uvicorn app:app --host 0.0.0.0 --port 8000
"""
import io
import os
import time
from contextlib import asynccontextmanager

import soundfile as sf
from fastapi import FastAPI, File, HTTPException, UploadFile

from stt import STT

# Đổi được bằng biến môi trường, không cần sửa code.
# 5 phút: trên CPU xử lý ~20–35s, vẫn dưới giới hạn chờ ~100s của tunnel Cloudflare.
MAX_AUDIO_SECONDS = int(os.environ.get("STT_MAX_SECONDS", 300))
# WAV 48 kHz stereo 16-bit nặng ~11.5 MB/phút -> 5 phút ~58 MB. Nên gửi MP3 (~1 MB/phút) cho nhẹ.
MAX_AUDIO_BYTES = int(os.environ.get("STT_MAX_MB", 60)) * 1024 * 1024
MIN_AUDIO_SECONDS = 0.3

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Chạy MỘT lần lúc khởi động. Server chỉ nhận request sau khi nạp xong model.
    print("Đang nạp PhoWhisper (faster-whisper int8)...", flush=True)
    state["stt"] = STT()
    stt = state["stt"]
    print(f"Đã nạp PhoWhisper trên {stt.device} trong {stt.load_seconds}s, chạy thử {stt.warmup_seconds}s.", flush=True)
    yield


app = FastAPI(title="STT API test - PhoWhisper", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "device": state["stt"].device}


@app.post("/transcribe")
def transcribe(audio: UploadFile = File(...)):
    # Đọc tối đa MAX + 1 byte: file quá lớn thì dừng luôn, không nạp hết vào RAM.
    data = audio.file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, f"File quá lớn (tối đa {MAX_AUDIO_BYTES // (1024 * 1024)} MB).")
    try:
        wav, sr = sf.read(io.BytesIO(data), dtype="float32")
    except Exception:
        raise HTTPException(400, "Không đọc được file audio (nhận WAV, FLAC, OGG, MP3).")

    duration = len(wav) / sr
    if duration < MIN_AUDIO_SECONDS:
        raise HTTPException(400, "Đoạn ghi âm quá ngắn.")
    if duration > MAX_AUDIO_SECONDS:
        raise HTTPException(400, f"Đoạn ghi âm quá dài (tối đa {MAX_AUDIO_SECONDS} giây).")

    t0 = time.perf_counter()
    text = state["stt"].transcribe(wav, sr)
    seconds = time.perf_counter() - t0
    print(f"[STT] {duration:.1f}s audio -> {seconds:.2f}s: {text}", flush=True)

    return {
        "text": text,
        "audio_duration": round(duration, 2),
        "processing_time": round(seconds, 2),
    }
