"""Tạo bộ audio test tải có độ dài CỐ ĐỊNH (10s, 30s, 60s), cắt từ đầu một file audio thật.

Độ dài cố định -> mỗi request tốn công như nhau, số đo giữa các lần test so sánh được với nhau.
Giữ nguyên tần số mẫu và số kênh của file gốc (giống audio người dùng gửi thật).

Chạy:  python loadtest/make_audio.py <file_audio_gốc> [thư_mục_ra]
Ví dụ: python loadtest/make_audio.py D:\\Hasssta_Project\\Audio_test\\VietComs1min.wav
-> loadtest/audio/test_10s.wav, test_30s.wav, test_60s.wav (file .wav không đưa lên Git)
"""
import sys
from pathlib import Path

import soundfile as sf

LENGTHS = [10, 30, 60]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)

    audio, sr = sf.read(src, dtype="int16")
    total = len(audio) / sr
    for sec in LENGTHS:
        if total < sec:
            print(f"[bỏ qua] {sec}s: file gốc chỉ dài {total:.1f}s")
            continue
        out = out_dir / f"test_{sec}s.wav"
        sf.write(out, audio[: sec * sr], sr, subtype="PCM_16")
        print(f"[tạo] {out} ({sec}s, {sr} Hz, {out.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
