"""Đo tốc độ PhoWhisper chạy bằng faster-whisper (CTranslate2) trên CPU.

Chưa đụng tới app.py / stt.py — chỉ để so sánh với cách đang dùng (transformers).

Chuẩn bị model (1 lần):
  ct2-transformers-converter --model vinai/PhoWhisper-small ^
      --output_dir models/PhoWhisper-small-int8 ^
      --quantization int8 --copy_files tokenizer.json preprocessor_config.json

Chạy:
  python bench/bench_faster_whisper.py <file.wav> <thư_mục_model> [số_luồng ...]
  Ví dụ: python bench/bench_faster_whisper.py D:\\Hasssta_Project\\VietComs30s.wav models\\PhoWhisper-small-int8 4 8 16
"""
import difflib
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
from faster_whisper import WhisperModel

# Dùng chung cách chia khung với API (stt.py ở thư mục cha) để số đo khớp với API thật.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stt import SAMPLE_RATE, split_windows  # noqa: E402

RUNS = 3

# Chữ do transformers (bản đang dùng trong API) trả về cho VietComs30s.wav — dùng làm mốc so sánh.
REFERENCE = (
    "hội thoại cùng nam và lan hội thoại cùng nam và lan chào lan dạo này thế nào rồi chào nam mình vẫn vậy "
    "nam thì sao ừm nam cũng thế không có gì thay đổi cả thế à trông nam gầy đi thì phải lan nghe nói nam mới "
    "đi tập di mà  ừ nam mới đi tập được một tuần trông gầy hơn rồi hả tốt quá đi."
)


def load_audio(path: str) -> np.ndarray:
    audio, sr = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SAMPLE_RATE:
        audio = soxr.resample(audio, sr, SAMPLE_RATE)
    return audio.astype(np.float32)


def transcribe(model: WhisperModel, audio: np.ndarray) -> str:
    texts = []
    for chunk in split_windows(audio):
        segments, _ = model.transcribe(
            chunk,
            language="vi",
            task="transcribe",
            beam_size=1,               # giống transformers mặc định (greedy) để so sánh công bằng
            without_timestamps=True,   # mốc thời gian của PhoWhisper hỏng -> bật lên sẽ nhảy sai, mất chữ
        )
        # segments là generator: phải duyệt hết thì model mới thật sự chạy
        texts.append(" ".join(s.text.strip() for s in segments))
    return " ".join(texts).strip()


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    audio_path, model_dir = sys.argv[1], sys.argv[2]
    thread_options = [int(x) for x in sys.argv[3:]] or [8]

    audio = load_audio(audio_path)
    duration = len(audio) / SAMPLE_RATE
    print(f"Audio: {duration:.2f}s\n")

    for threads in thread_options:
        t0 = time.perf_counter()
        model = WhisperModel(model_dir, device="cpu", compute_type="int8", cpu_threads=threads)
        load_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        transcribe(model, audio[: 2 * SAMPLE_RATE])   # chạy thử 2 giây cho "ấm máy"
        warm_s = time.perf_counter() - t0

        times, text = [], ""
        for _ in range(RUNS):
            t0 = time.perf_counter()
            text = transcribe(model, audio)
            times.append(time.perf_counter() - t0)

        similar = difflib.SequenceMatcher(None, text.lower(), REFERENCE.lower()).ratio() * 100
        print(f"=== {threads} luồng | nạp {load_s:.1f}s | chạy thử {warm_s:.1f}s")
        print("    các lần: " + ", ".join(f"{t:.2f}s" for t in times)
              + f" | trung bình {np.mean(times):.2f}s | nhanh hơn thời gian thực {duration / np.mean(times):.1f} lần")
        print(f"    giống bản transformers: {similar:.1f}%")
        print(f"    chữ: {text}\n")
        del model


if __name__ == "__main__":
    main()
