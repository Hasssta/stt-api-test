"""API PhoWhisper (chạy CPU bằng faster-whisper int8).

  GET  /             -> trang giao diện (nhập key, chọn file, xem chữ)
  GET  /health       -> server còn sống không, model chạy trên thiết bị nào
  POST /transcribe   -> gửi 1 file audio (WAV, FLAC, OGG, MP3), nhận lại chữ
                        (bắt buộc có header X-API-Key, sai/thiếu -> 401;
                         hàng đợi đầy -> 503, đổi số chỗ chờ bằng STT_MAX_QUEUE)

Chạy: uvicorn app:app --host 0.0.0.0 --port 8000
"""
import io
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager

import soundfile as sf
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from stt import STT

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
INDEX_HTML = os.path.join(STATIC_DIR, "index.html")

# Đọc file .env (nếu có) vào biến môi trường. Biến đã đặt sẵn trên máy thì được ưu tiên.
load_dotenv()

# Khóa bí mật: KHÔNG ghi vào code. Đặt trong file .env hoặc biến môi trường.
#   STT_API_KEY  = key của chủ server (bắt buộc)
#   STT_API_KEYS = key cấp cho người khác, dạng "ten:key,ten2:key2" (tùy chọn).
#                  Mỗi người một key -> lộ key của ai thì xóa riêng key đó; log ghi tên người gọi.
API_KEY = os.environ.get("STT_API_KEY", "").strip()
MIN_API_KEY_LENGTH = 16


def parse_keys(owner_key: str, extra: str) -> dict[str, str]:
    """Trả {tên: key}. Báo lỗi ngay lúc khởi động nếu khai báo sai, thay vì âm thầm bỏ qua."""
    keys = {"owner": owner_key}
    for item in filter(None, (s.strip() for s in extra.split(","))):
        name, sep, key = item.partition(":")
        name, key = name.strip(), key.strip()
        if not sep or not name or not key:
            raise RuntimeError(f"STT_API_KEYS sai định dạng ở mục thứ {len(keys)} (cần ten:key).")
        if name in keys:
            raise RuntimeError(f"STT_API_KEYS: tên '{name}' bị trùng.")
        if len(key) < MIN_API_KEY_LENGTH:
            raise RuntimeError(f"STT_API_KEYS: key của '{name}' cần ít nhất {MIN_API_KEY_LENGTH} ký tự.")
        if key in keys.values():
            raise RuntimeError(f"STT_API_KEYS: key của '{name}' trùng với một key khác.")
        keys[name] = key
    return keys


API_KEYS: dict[str, str] = {}   # điền trong lifespan, sau khi kiểm tra hợp lệ

# Đổi được bằng biến môi trường, không cần sửa code.
# 5 phút: trên CPU xử lý ~20–35s, vẫn dưới giới hạn chờ ~100s của tunnel Cloudflare.
MAX_AUDIO_SECONDS = int(os.environ.get("STT_MAX_SECONDS", 300))
# WAV 48 kHz stereo 16-bit nặng ~11.5 MB/phút -> 5 phút ~58 MB. Nên gửi MP3 (~1 MB/phút) cho nhẹ.
MAX_AUDIO_BYTES = int(os.environ.get("STT_MAX_MB", 60)) * 1024 * 1024
MIN_AUDIO_SECONDS = 0.3
# Số request được XẾP HÀNG CHỜ (ngoài 1 request đang xử lý). Hàng đầy -> trả 503 ngay,
# không để người gọi chờ mãi rồi hết thời gian. Mặc định 4: 30s audio xử lý ~3s nên người thứ 5
# chờ ~15s; audio 5 phút (~30s/request) thì chờ tới ~150s -> nên giảm nếu audio dài.
MAX_QUEUE = int(os.environ.get("STT_MAX_QUEUE", 4))

state: dict = {}


class Admission:
    """Đếm số request đang ở trong server (đang xử lý + đang chờ), từ chối khi vượt giới hạn."""

    def __init__(self, limit: int):
        self.limit = limit
        self.count = 0
        self._lock = threading.Lock()

    def try_enter(self) -> bool:
        with self._lock:
            if self.count >= self.limit:
                return False
            self.count += 1
            return True

    def leave(self):
        with self._lock:
            self.count -= 1


# Model xử lý 1 request mỗi lúc (khóa trong stt.py) -> tối đa 1 đang chạy + MAX_QUEUE đang chờ.
admission = Admission(1 + MAX_QUEUE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Chạy MỘT lần lúc khởi động. Server chỉ nhận request sau khi nạp xong model.
    # Thiếu key thì không chạy, để không bao giờ vô tình mở API cho mọi người.
    if MAX_QUEUE < 0:
        raise RuntimeError("STT_MAX_QUEUE phải >= 0.")
    if len(API_KEY) < MIN_API_KEY_LENGTH:
        raise RuntimeError(
            f"Chưa đặt STT_API_KEY (cần ít nhất {MIN_API_KEY_LENGTH} ký tự). "
            "Chép .env.example thành .env rồi điền key vào."
        )
    API_KEYS.update(parse_keys(API_KEY, os.environ.get("STT_API_KEYS", "")))
    # Chỉ in TÊN, không bao giờ in key.
    print(f"Có {len(API_KEYS)} API key: {', '.join(API_KEYS)}", flush=True)
    print("Đang nạp PhoWhisper (faster-whisper int8)...", flush=True)
    state["stt"] = STT()
    stt = state["stt"]
    print(f"Đã nạp PhoWhisper trên {stt.device} trong {stt.load_seconds}s, chạy thử {stt.warmup_seconds}s.", flush=True)
    yield


app = FastAPI(title="STT API test - PhoWhisper", lifespan=lifespan)
# CSS/JS của trang giao diện: static/css/, static/js/ -> phục vụ ở /static/... (không cần key)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """Trả tên chủ của key. compare_digest so sánh với thời gian cố định, không để lộ key
    qua thời gian phản hồi; so với MỌI key (không dừng sớm) để không lộ key nào khớp.
    Đổi sang bytes vì compare_digest không nhận chuỗi có ký tự ngoài ASCII."""
    caller = None
    if x_api_key is not None:
        given = x_api_key.encode()
        for name, key in API_KEYS.items():
            if secrets.compare_digest(given, key.encode()):
                caller = name
    if caller is None:
        raise HTTPException(401, "Thiếu hoặc sai API key (gửi qua header X-API-Key).")
    return caller


@app.get("/", include_in_schema=False)
def index():
    # Trang giao diện. Không chứa bí mật nên không cần key; key do người dùng nhập trên trang.
    return FileResponse(INDEX_HTML)


@app.get("/health")
def health():
    # Không cần key: chỉ để kiểm tra server còn sống, không lộ thông tin nhạy cảm.
    # in_queue: số request đang ở trong server (đang xử lý + đang chờ) -> tiện theo dõi khi test tải.
    return {
        "status": "ok",
        "device": state["stt"].device,
        "in_queue": admission.count,
        "max_queue": MAX_QUEUE,
    }


@app.post("/transcribe")
def transcribe(audio: UploadFile = File(...), caller: str = Depends(require_api_key)):
    # Kiểm tra hàng đợi TRƯỚC khi đọc/giải mã file: lúc quá tải thì từ chối rẻ nhất có thể.
    if not admission.try_enter():
        print(f"[{caller}] 503 hàng đợi đầy", flush=True)
        raise HTTPException(
            503,
            "Server đang bận, vui lòng thử lại sau ít giây.",
            headers={"Retry-After": "5"},
        )
    try:
        result = _transcribe(audio)
        print(f"[{caller}] {result['audio_duration']}s audio, xử lý {result['processing_time']}s", flush=True)
        return result
    finally:
        admission.leave()


def _transcribe(audio: UploadFile) -> dict:
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
