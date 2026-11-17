"""PhoWhisper: giọng nói -> chữ, chạy thuần CPU bằng faster-whisper (CTranslate2, int8).

Nạp model MỘT lần khi server khởi động, dùng lại cho mọi request.

Model phải được chuyển đổi trước (1 lần) sang định dạng CTranslate2 — xem README / requirements-convert.txt:
  ct2-transformers-converter --model vinai/PhoWhisper-small --output_dir models/PhoWhisper-small-int8 \
      --quantization int8 --copy_files tokenizer.json preprocessor_config.json

Cấu hình qua biến môi trường (không bắt buộc):
  STT_MODEL_DIR    thư mục model đã chuyển đổi (mặc định: models/PhoWhisper-small-int8 cạnh file này)
  STT_CPU_THREADS  số luồng CPU cho model (mặc định: số nhân thật ≈ số luồng logic / 2)
  STT_MIN_LOGPROB  độ tự tin tối thiểu, đoạn chữ thấp hơn bị bỏ vì là chữ bịa (mặc định -0.3)

Chống "bịa chữ": PhoWhisper đưa vào im lặng/nhiễu vẫn ra một câu trơn tru (vd 3s im lặng ->
"tuy nhiên không phải ai cũng có thể thực hiện điều này."). Cờ no_speech_prob của Whisper luôn = 0
với PhoWhisper nên không dùng được. Thay vào đó lọc 2 lớp (đo trên 25 file Audio_test, gốc + 8 kHz):
  1. Trước model: khung chỉ toàn im lặng / nhiễu đều -> bỏ qua, không gọi model (tiết kiệm CPU).
     Tiếng nói lên xuống 25-75 dB; im lặng, nhiễu, tiếng ù gần như phẳng (~1 dB).
  2. Sau model: đoạn có avg_logprob < STT_MIN_LOGPROB -> bỏ. Chữ thật: -0.00..-0.12; chữ bịa: -0.49..-0.92.
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
SPEECH_MIN_DB = -45                   # phần to của khung (phân vị 95) phải lớn hơn mức này (dBFS) mới có thể là tiếng nói
SPEECH_MIN_RANGE_DB = 10              # và âm lượng phải lên xuống hơn 10 dB (phân vị 95 - phân vị 10)
DEFAULT_MIN_LOGPROB = -0.3            # chữ có độ tự tin thấp hơn bị coi là bịa

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


def has_speech(chunk: np.ndarray) -> bool:
    """Khung có thể chứa tiếng nói không, chỉ dựa vào âm lượng (lớp lọc 1).

    Im lặng: quá nhỏ. Nhiễu đều / tiếng ù điện: to nhỏ gần như không đổi. Tiếng nói: có âm tiết
    và chỗ ngắt nên âm lượng lên xuống mạnh. Ngưỡng để rộng (thật đo được >= 25 dB) cho an toàn.
    """
    n = len(chunk) // FRAME
    if n == 0:
        return False
    rms = np.sqrt((chunk[: n * FRAME].reshape(n, FRAME) ** 2).mean(axis=1))
    db = 20 * np.log10(rms + 1e-9)
    loud, floor = np.percentile(db, 95), np.percentile(db, 10)
    return loud > SPEECH_MIN_DB and loud - floor > SPEECH_MIN_RANGE_DB


class STT:
    def __init__(self):
        model_dir = Path(os.environ.get("STT_MODEL_DIR", DEFAULT_MODEL_DIR))
        if not (model_dir / "model.bin").exists():
            raise RuntimeError(
                f"Không thấy model ở {model_dir}. Hãy chuyển đổi PhoWhisper sang CTranslate2 trước (xem README)."
            )
        self.threads = int(os.environ.get("STT_CPU_THREADS", max(1, (os.cpu_count() or 2) // 2)))
        self.device = f"cpu ({self.threads} luồng, int8)"
        try:
            self.min_logprob = float(os.environ.get("STT_MIN_LOGPROB", DEFAULT_MIN_LOGPROB))
        except ValueError:
            raise RuntimeError("STT_MIN_LOGPROB phải là số, ví dụ -0.3") from None

        t0 = time.perf_counter()
        self.model = WhisperModel(str(model_dir), device="cpu", compute_type="int8", cpu_threads=self.threads)
        self.load_seconds = round(time.perf_counter() - t0, 1)

        # Mỗi lúc chỉ xử lý MỘT request (dùng hết số luồng đã chọn) -> nhiều người gửi cùng lúc thì xếp hàng.
        self._lock = threading.Lock()

        # Chạy thử model 1 lần để request đầu tiên không bị chậm. Gọi thẳng _decode, vì transcribe()
        # sẽ bỏ qua 2 giây im lặng này (lớp lọc 1) và model không thật sự chạy.
        t0 = time.perf_counter()
        self._decode(np.zeros(2 * SAMPLE_RATE, dtype=np.float32))
        self.warmup_seconds = round(time.perf_counter() - t0, 1)

    def _decode(self, chunk: np.ndarray) -> str:
        """Nhận dạng 1 khung <= 30 giây, bỏ các đoạn chữ có độ tự tin thấp (lớp lọc 2)."""
        segments, _ = self.model.transcribe(
            chunk,
            language="vi",               # luôn nhận tiếng Việt, bỏ bước đoán ngôn ngữ
            task="transcribe",
            beam_size=1,                 # greedy: nhanh; beam 5 chậm hơn ~40% mà không tốt hơn khi thử
            without_timestamps=True,     # mốc thời gian của PhoWhisper hỏng -> bật lên sẽ nhảy sai, mất chữ
        )
        # segments là generator: phải duyệt hết thì model mới thật sự chạy
        return " ".join(s.text.strip() for s in segments if s.avg_logprob >= self.min_logprob)

    def transcribe(self, audio: np.ndarray, sr: int) -> str:
        if audio.ndim > 1:                 # stereo -> mono
            audio = audio.mean(axis=1)
        if sr != SAMPLE_RATE:              # chuyển về 16 kHz nếu file gửi lên khác
            audio = soxr.resample(audio, sr, SAMPLE_RATE)
        audio = audio.astype(np.float32)

        texts = []
        with self._lock:
            for chunk in split_windows(audio):
                if has_speech(chunk):        # khung toàn im lặng / nhiễu đều -> không gọi model
                    texts.append(self._decode(chunk))
        return " ".join(t for t in texts if t).strip()
