"""Ví dụ gọi STT API từ máy bất kỳ (gửi cho bạn bè dùng thử).

Cài:  pip install requests
Chạy: python client_example.py https://xxxx.trycloudflare.com duong_dan/file.wav
"""
import sys

import requests


def main():
    if len(sys.argv) != 3:
        print("Cách dùng: python client_example.py <LINK_SERVER> <FILE_WAV>")
        sys.exit(1)
    server = sys.argv[1].rstrip("/")
    path = sys.argv[2]

    with open(path, "rb") as f:
        r = requests.post(f"{server}/transcribe", files={"audio": (path, f, "audio/wav")}, timeout=300)

    if r.ok:
        data = r.json()
        print("Chữ:", data["text"])
        print(f"Audio {data['audio_duration']}s, xử lý {data['processing_time']}s")
    else:
        # Server trả lỗi dạng {"detail": "..."}; tunnel lỗi thì có thể là HTML -> in nguyên văn
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:300]
        print(f"Lỗi {r.status_code}: {detail}")


if __name__ == "__main__":
    main()
