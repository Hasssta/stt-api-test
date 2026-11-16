"""Kịch bản test tải bằng Locust: mỗi "người dùng" gửi 1 file audio, chờ kết quả, nghỉ 1–2 giây, gửi tiếp.

Cấu hình qua biến môi trường:
  STT_API_KEY      API key (nếu không đặt, đọc từ file .env của project)
  LOADTEST_LENGTH  độ dài audio gửi đi: 10, 30 hoặc 60 (mặc định 30) -> dùng loadtest/audio/test_<n>s.wav

Chạy không giao diện, ví dụ 10 người, mỗi giây thêm 2 người, chạy 3 phút, lưu kết quả CSV:
  locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 --headless `
      -u 10 -r 2 -t 3m --csv loadtest/results/u10_30s

Chạy có giao diện web (mở http://localhost:8089):
  locust -f loadtest/locustfile.py --host http://127.0.0.1:8000

Mã lỗi được ghi riêng để dễ đọc kết quả: 503 = server bận (hàng đợi đầy), 401 = sai key.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from locust import HttpUser, between, task

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API_KEY = os.environ.get("STT_API_KEY", "").strip()
LENGTH = int(os.environ.get("LOADTEST_LENGTH", 30))
AUDIO_PATH = Path(__file__).parent / "audio" / f"test_{LENGTH}s.wav"

if not API_KEY:
    raise RuntimeError("Chưa có STT_API_KEY (đặt biến môi trường hoặc điền vào .env).")
if not AUDIO_PATH.exists():
    raise RuntimeError(f"Không thấy {AUDIO_PATH}. Chạy loadtest/make_audio.py trước.")

# Đọc file một lần, mọi người dùng ảo dùng chung -> không tốn RAM / ổ đĩa phía máy test.
AUDIO_BYTES = AUDIO_PATH.read_bytes()


class SttUser(HttpUser):
    wait_time = between(1, 2)   # nghỉ giữa 2 lần gửi, giống người thật thao tác

    @task
    def transcribe(self):
        with self.client.post(
            "/transcribe",
            headers={"X-API-Key": API_KEY},
            files={"audio": (AUDIO_PATH.name, AUDIO_BYTES, "audio/wav")},
            name=f"/transcribe [{LENGTH}s]",
            timeout=600,
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                r.success()
            elif r.status_code == 503:
                r.failure("503 server bận (hàng đợi đầy)")
            elif r.status_code == 401:
                r.failure("401 sai API key")
            else:
                r.failure(f"{r.status_code}: {r.text[:100]}")
