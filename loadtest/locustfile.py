"""Kịch bản test tải bằng Locust: mỗi "người dùng" gửi 1 file audio, chờ kết quả, nghỉ 1–2 giây, gửi tiếp.

Chọn audio gửi đi (ô "Audio" trên giao diện web, hoặc --audio khi chạy dòng lệnh):
  - đường dẫn 1 FILE (WAV/MP3/FLAC/OGG)  -> mọi request gửi file đó
  - đường dẫn 1 THƯ MỤC                  -> mỗi request chọn ngẫu nhiên 1 file trong thư mục
  - bỏ trống -> dùng loadtest/audio/test_<LOADTEST_LENGTH>s.wav (LOADTEST_LENGTH: 10, 30, 60; mặc định 30)
Kết quả được thống kê riêng theo từng tên file.

API key: biến môi trường STT_API_KEY, nếu không đặt thì đọc từ file .env của project.

Chạy có giao diện web (mở http://localhost:8089):
  locust -f loadtest/locustfile.py --host http://127.0.0.1:8000

Chạy không giao diện, ví dụ 10 người, mỗi giây thêm 2 người, 3 phút, lưu CSV:
  locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 --headless `
      -u 10 -r 2 -t 3m --csv loadtest/results/u10_30s --audio D:\\duong_dan\\file.wav

Mã lỗi được ghi riêng để dễ đọc kết quả: 503 = server bận (hàng đợi đầy), 401 = sai key,
400/413 = file không hợp lệ hoặc vượt giới hạn của server.
"""
import os
import random
from pathlib import Path

from dotenv import load_dotenv
from locust import HttpUser, between, events, task

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API_KEY = os.environ.get("STT_API_KEY", "").strip()
if not API_KEY:
    raise RuntimeError("Chưa có STT_API_KEY (đặt biến môi trường hoặc điền vào .env).")

DEFAULT_AUDIO = Path(__file__).parent / "audio" / f"test_{int(os.environ.get('LOADTEST_LENGTH', 30))}s.wav"
AUDIO_EXT = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".ogg": "audio/ogg"}


@events.init_command_line_parser.add_listener
def add_audio_option(parser):
    # include_in_web_ui: hiện thành ô nhập trên giao diện web, đổi được trước mỗi lần bấm START.
    parser.add_argument("--audio", type=str, default=str(DEFAULT_AUDIO), include_in_web_ui=True,
                        help="Đường dẫn 1 file audio, hoặc 1 thư mục (chọn ngẫu nhiên file trong đó)")


_cache: dict[str, list[tuple[str, bytes, str]]] = {}


def load_audio(path_text: str) -> list[tuple[str, bytes, str]]:
    """Đọc file (hoặc mọi file audio trong thư mục) một lần, các người dùng ảo dùng chung."""
    path_text = path_text.strip().strip('"')
    if path_text not in _cache:
        p = Path(path_text)
        files = sorted(f for f in p.iterdir() if f.suffix.lower() in AUDIO_EXT) if p.is_dir() else [p]
        if not files or not all(f.is_file() for f in files):
            raise FileNotFoundError(f"Không thấy file audio ở: {path_text}")
        _cache[path_text] = [(f.name, f.read_bytes(), AUDIO_EXT.get(f.suffix.lower(), "application/octet-stream"))
                             for f in files]
        print(f"[audio] {len(files)} file từ {path_text}")
    return _cache[path_text]


@events.test_start.add_listener
def check_audio(environment, **kwargs):
    # Báo lỗi ngay khi bấm START nếu đường dẫn sai, thay vì để mọi request đều lỗi.
    try:
        load_audio(environment.parsed_options.audio)
    except Exception as e:
        print(f"[audio] LỖI: {e}")


class SttUser(HttpUser):
    wait_time = between(1, 2)   # nghỉ giữa 2 lần gửi, giống người thật thao tác

    @task
    def transcribe(self):
        try:
            name, data, mime = random.choice(load_audio(self.environment.parsed_options.audio))
        except Exception as e:
            events.request.fire(request_type="POST", name="/transcribe [lỗi đường dẫn audio]",
                                response_time=0, response_length=0, exception=e)
            return

        with self.client.post(
            "/transcribe",
            headers={"X-API-Key": API_KEY},
            files={"audio": (name, data, mime)},
            name=f"/transcribe [{name}]",
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
