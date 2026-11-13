"""API PhoWhisper (chạy CPU bằng faster-whisper int8).

  GET  /             -> trang giao diện (nhập key, chọn file, xem chữ)
  GET  /health       -> server còn sống không, model chạy trên thiết bị nào
  POST /transcribe   -> gửi 1 file audio (WAV, FLAC, OGG, MP3), nhận lại chữ
                        (bắt buộc có header X-API-Key, sai/thiếu -> 401)

Chạy: uvicorn app:app --host 0.0.0.0 --port 8000
"""
import io
import os
import secrets
import time
from contextlib import asynccontextmanager

import soundfile as sf
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from stt import STT

INDEX_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")

# Đọc file .env (nếu có) vào biến môi trường. Biến đã đặt sẵn trên máy thì được ưu tiên.
load_dotenv()

# Khóa bí mật: KHÔNG ghi vào code. Đặt trong file .env hoặc biến môi trường STT_API_KEY.
API_KEY = os.environ.get("STT_API_KEY", "").strip()
MIN_API_KEY_LENGTH = 16

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
    # Thiếu key thì không chạy, để không bao giờ vô tình mở API cho mọi người.
    if len(API_KEY) < MIN_API_KEY_LENGTH:
        raise RuntimeError(
            f"Chưa đặt STT_API_KEY (cần ít nhất {MIN_API_KEY_LENGTH} ký tự). "
            "Chép .env.example thành .env rồi điền key vào."
        )
    print("Đang nạp PhoWhisper (faster-whisper int8)...", flush=True)
    state["stt"] = STT()
    stt = state["stt"]
    print(f"Đã nạp PhoWhisper trên {stt.device} trong {stt.load_seconds}s, chạy thử {stt.warmup_seconds}s.", flush=True)
    yield


app = FastAPI(title="STT API test - PhoWhisper", lifespan=lifespan)


def require_api_key(x_api_key: str | None = Header(default=None)):
    # compare_digest so sánh với thời gian cố định, không để lộ key qua thời gian phản hồi.
    # Đổi sang bytes vì compare_digest không nhận chuỗi có ký tự ngoài ASCII.
    if x_api_key is None or not secrets.compare_digest(x_api_key.encode(), API_KEY.encode()):
        raise HTTPException(401, "Thiếu hoặc sai API key (gửi qua header X-API-Key).")


@app.get("/", include_in_schema=False)
def index():
    # Trang giao diện. Không chứa bí mật nên không cần key; key do người dùng nhập trên trang.
    return FileResponse(INDEX_HTML)


@app.get("/health")
def health():
    # Không cần key: chỉ để kiểm tra server còn sống, không lộ thông tin nhạy cảm.
    return {"status": "ok", "device": state["stt"].device}


@app.post("/transcribe", dependencies=[Depends(require_api_key)])
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
