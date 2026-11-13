"""Bước 1: API tối thiểu cho PhoWhisper.

  GET  /health       -> server còn sống không, model chạy trên thiết bị nào
  POST /transcribe   -> gửi 1 file audio (WAV), nhận lại chữ

Chạy: uvicorn app:app --host 0.0.0.0 --port 8000
"""
import io
import time
from contextlib import asynccontextmanager

import soundfile as sf
from fastapi import FastAPI, File, HTTPException, UploadFile

from stt import STT

# WAV 48 kHz stereo 16-bit nặng ~11.5 MB/phút (32-bit gấp đôi) -> để 25 MB.
# Giới hạn chính vẫn là độ dài MAX_AUDIO_SECONDS.
MAX_AUDIO_BYTES = 25 * 1024 * 1024   # 25 MB
MAX_AUDIO_SECONDS = 60
MIN_AUDIO_SECONDS = 0.3

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Chạy MỘT lần lúc khởi động. Server chỉ nhận request sau khi nạp xong model.
    print("Đang nạp PhoWhisper (lần đầu phải tải model khoảng 1 GB)...", flush=True)
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
        raise HTTPException(400, "Không đọc được file audio (bước này mới nhận WAV).")

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
