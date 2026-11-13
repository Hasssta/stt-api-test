"""PhoWhisper: giọng nói -> chữ, chạy thuần CPU bằng faster-whisper (CTranslate2, int8).

Nạp model MỘT lần khi server khởi động, dùng lại cho mọi request.

Model phải được chuyển đổi trước (1 lần) sang định dạng CTranslate2 — xem README / requirements-convert.txt:
  ct2-transformers-converter --model vinai/PhoWhisper-small --output_dir models/PhoWhisper-small-int8 \
      --quantization int8 --copy_files tokenizer.json preprocessor_config.json

Cấu hình qua biến môi trường (không bắt buộc):
  STT_MODEL_DIR    thư mục model đã chuyển đổi (mặc định: models/PhoWhisper-small-int8 cạnh file này)
  STT_CPU_THREADS  số luồng CPU cho model (mặc định: số nhân thật ≈ số luồng logic / 2)
"""
import os
import threading
import time
from pathlib import Path

import numpy as np
import soxr
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000                   # PhoWhisper (giống Whisper) cần audio 16 kHz
WINDOW = 30 * SAMPLE_RATE             # Whisper luôn xử lý theo khung 30 giây
TINY_TAIL = int(0.5 * SAMPLE_RATE)    # phần dư nhỏ hơn mức này thì bỏ, không tạo khung gần như rỗng
SEARCH = 5 * SAMPLE_RATE              # tìm chỗ ngắt trong 5 giây cuối của mỗi khung
FRAME = int(0.02 * SAMPLE_RATE)       # đo âm lượng theo từng 20 ms
SILENCE_DB = 25                       # khung nhỏ hơn mức nói (phân vị 90) 25 dB được tính là "lặng"

DEFAULT_MODEL_DIR = Path(__file__).parent / "models" / "PhoWhisper-small-int8"


def _best_cut(seg: np.ndarray) -> int:
    """Vị trí (tính bằng mẫu) nên cắt trong seg: GIỮA KHOẢNG LẶNG DÀI NHẤT.

    Chọn khoảng lặng dài nhất chứ không phải chỗ nhỏ tiếng nhất: người nói ngừng lâu ở cuối câu,
    còn chỗ ngập ngừng giữa câu thường ngắn. (Đã thử trên VietComs1min.wav: chỗ nhỏ tiếng nhất là
    một khoảng ngừng 0.3s giữa câu -> cắt ở đó làm sai chữ; khoảng lặng 0.6s ngay sau mới là hết câu.)
    """
    n = len(seg) // FRAME
    rms = np.sqrt((seg[: n * FRAME].reshape(n, FRAME) ** 2).mean(axis=1))
    db = 20 * np.log10(rms + 1e-9)
    # Ngưỡng tính theo mức NÓI (không theo mức nhỏ nhất): vài khung cực nhỏ không kéo ngưỡng xuống quá thấp.
    quiet = db <= np.percentile(db, 90) - SILENCE_DB

    best_len, best_mid, run_start = 0, int(np.argmin(db)), None
    for i, q in enumerate(np.append(quiet, False)):   # thêm False ở cuối để đóng khoảng lặng cuối cùng
        if q and run_start is None:
            run_start = i
        elif not q and run_start is not None:
            if i - run_start >= best_len:              # >= : bằng nhau thì lấy khoảng muộn hơn (khung dài hơn)
                best_len, best_mid = i - run_start, (run_start + i) // 2
            run_start = None
    return best_mid * FRAME + FRAME // 2


def split_windows(audio: np.ndarray) -> list[np.ndarray]:
    """Chia audio thành các khung <= 30 giây, cắt ở CHỖ NGẮT NGHỈ chứ không cắt giữa câu.

    - Mỗi khung dài tối đa 30s. Trong 5 giây cuối của khung, tìm khoảng lặng dài nhất (thường là
      chỗ hết câu) rồi cắt ở giữa nó. Chỉ đo âm lượng, không bỏ đi phần audio nào -> không mất chữ.
      (Đã thử: chia đều cắt ngang câu "anh là ai đấy ạ" -> "anh là ai. em đi ạ"; cắt ở chỗ ngắt thì đúng.)
    - Không để sót khung gần như rỗng (vd file 30.04s -> khung 0.04s): model sẽ "bịa chữ" trên
      phần im lặng được đệm thêm. Phần dư <= 0.5s thì bỏ.
    """
    chunks, start = [], 0
    while len(audio) - start > WINDOW + TINY_TAIL:
        lo = start + WINDOW - SEARCH
        cut = lo + _best_cut(audio[lo:start + WINDOW])
        chunks.append(audio[start:cut])
        start = cut
    chunks.append(audio[start:start + WINDOW])
    return chunks


class STT:
    def __init__(self):
        model_dir = Path(os.environ.get("STT_MODEL_DIR", DEFAULT_MODEL_DIR))
        if not (model_dir / "model.bin").exists():
            raise RuntimeError(
                f"Không thấy model ở {model_dir}. Hãy chuyển đổi PhoWhisper sang CTranslate2 trước (xem README)."
            )
        self.threads = int(os.environ.get("STT_CPU_THREADS", max(1, (os.cpu_count() or 2) // 2)))
        self.device = f"cpu ({self.threads} luồng, int8)"

        t0 = time.perf_counter()
        self.model = WhisperModel(str(model_dir), device="cpu", compute_type="int8", cpu_threads=self.threads)
        self.load_seconds = round(time.perf_counter() - t0, 1)

        # Mỗi lúc chỉ xử lý MỘT request (dùng hết số luồng đã chọn) -> nhiều người gửi cùng lúc thì xếp hàng.
        self._lock = threading.Lock()

        # Chạy thử 1 lần với 2 giây im lặng ở 48 kHz để request đầu tiên không bị chậm.
        t0 = time.perf_counter()
        self.transcribe(np.zeros(2 * 48000, dtype=np.float32), 48000)
        self.warmup_seconds = round(time.perf_counter() - t0, 1)

    def transcribe(self, audio: np.ndarray, sr: int) -> str:
        if audio.ndim > 1:                 # stereo -> mono
            audio = audio.mean(axis=1)
        if sr != SAMPLE_RATE:              # chuyển về 16 kHz nếu file gửi lên khác
            audio = soxr.resample(audio, sr, SAMPLE_RATE)
        audio = audio.astype(np.float32)

        texts = []
        with self._lock:
            for chunk in split_windows(audio):
                segments, _ = self.model.transcribe(
                    chunk,
                    language="vi",               # luôn nhận tiếng Việt, bỏ bước đoán ngôn ngữ
                    task="transcribe",
                    beam_size=1,                 # greedy: nhanh; beam 5 chậm hơn ~40% mà không tốt hơn khi thử
                    without_timestamps=True,     # mốc thời gian của PhoWhisper hỏng -> bật lên sẽ nhảy sai, mất chữ
                )
                # segments là generator: phải duyệt hết thì model mới thật sự chạy
                texts.append(" ".join(s.text.strip() for s in segments))
        return " ".join(texts).strip()
