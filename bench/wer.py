"""Đo độ chính xác (WER) của PhoWhisper, dùng ĐÚNG cách nhận dạng của API (stt.py).

Hai bước:
  1) Tạo bản nháp: model nhận dạng từng file audio, lưu chữ ra file .txt cùng tên, cạnh file audio.
     File .txt đã có thì GIỮ NGUYÊN (không ghi đè bản bạn đã sửa).
       python bench/wer.py draft <thư_mục_audio> [mẫu_tên_file]
  2) Nghe lại và sửa từng file .txt cho đúng từng chữ -> thành bản ghi chuẩn.
  3) Tính WER: so chữ model với bản chuẩn, in lỗi từng file và WER tổng.
       python bench/wer.py score <thư_mục_audio> [mẫu_tên_file]

Mẫu tên file mặc định: *.wav. Ví dụ:
  python bench/wer.py draft D:\\Hasssta_Project\\Audio_test "audio_*.wav"

WER = (thay + thiếu + thừa) / số từ của bản chuẩn.
Trước khi so: đưa về chữ thường, chuẩn hóa Unicode (NFC), bỏ dấu câu -> dấu chấm, chữ hoa không bị tính là lỗi.
Chưa quy đổi số: "2" và "hai" vẫn bị tính là khác nhau.
"""
import re
import sys
import time
import unicodedata
from pathlib import Path

import soundfile as sf

# Dùng chung lớp STT với API (stt.py ở thư mục cha) để kết quả khớp với API thật.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stt import STT  # noqa: E402


def normalize(text: str) -> list[str]:
    # NFC: cùng một chữ "ệ" có thể được lưu bằng 1 hoặc nhiều mã Unicode -> đưa về một dạng.
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)   # bỏ dấu câu, giữ chữ (kể cả chữ có dấu) và số
    return text.split()


def align(ref: list[str], hyp: list[str]) -> list[tuple[str, str, str]]:
    """So khớp từng từ (khoảng cách Levenshtein). Trả về danh sách (loại, từ chuẩn, từ model).

    loại: "ok" đúng, "sub" thay, "del" thiếu (model bỏ mất), "ins" thừa (model thêm vào).
    """
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j - 1] + cost, d[i - 1][j] + 1, d[i][j - 1] + 1)

    ops, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("ok" if ref[i - 1] == hyp[j - 1] else "sub", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            ops.append(("del", ref[i - 1], ""))
            i -= 1
        else:
            ops.append(("ins", "", hyp[j - 1]))
            j -= 1
    return ops[::-1]


def show_errors(ops) -> str:
    # Viết lại câu chuẩn, đánh dấu lỗi: [chuẩn→model] thay, [-từ] thiếu, [+từ] thừa.
    out = []
    for kind, r, h in ops:
        out.append({"ok": r, "sub": f"[{r}→{h}]", "del": f"[-{r}]", "ins": f"[+{h}]"}[kind])
    return " ".join(out)


def list_audio(folder: Path, pattern: str) -> list[Path]:
    files = sorted(folder.glob(pattern))
    if not files:
        print(f"Không thấy file nào khớp {pattern} trong {folder}")
        sys.exit(1)
    return files


def run_stt(stt: STT, path: Path) -> tuple[str, float, float]:
    wav, sr = sf.read(path, dtype="float32")
    t0 = time.perf_counter()
    text = stt.transcribe(wav, sr)
    return text, len(wav) / sr, time.perf_counter() - t0


def draft(folder: Path, pattern: str):
    files = list_audio(folder, pattern)
    stt = STT()
    print(f"Model: {stt.device}\n")
    made = 0
    for path in files:
        txt = path.with_suffix(".txt")
        if txt.exists():
            print(f"[giữ nguyên] {txt.name} đã có")
            continue
        text, dur, sec = run_stt(stt, path)
        txt.write_text(text + "\n", encoding="utf-8")
        made += 1
        print(f"[tạo] {txt.name} ({dur:.1f}s audio, {sec:.2f}s xử lý): {text}")
    print(f"\nĐã tạo {made} bản nháp. Hãy nghe lại và sửa từng file .txt cho đúng, rồi chạy: score")


def score(folder: Path, pattern: str):
    files = [p for p in list_audio(folder, pattern) if p.with_suffix(".txt").exists()]
    if not files:
        print("Chưa có file .txt nào (bản chuẩn). Chạy draft trước.")
        sys.exit(1)
    stt = STT()
    print(f"Model: {stt.device}\n")

    total_err = total_words = 0
    total_audio = total_sec = 0.0
    rows = []
    for path in files:
        ref = normalize(path.with_suffix(".txt").read_text(encoding="utf-8"))
        if not ref:
            print(f"[bỏ qua] {path.stem}.txt rỗng")
            continue
        text, dur, sec = run_stt(stt, path)
        ops = align(ref, normalize(text))
        err = sum(kind != "ok" for kind, _, _ in ops)
        total_err += err
        total_words += len(ref)
        total_audio += dur
        total_sec += sec
        rows.append((path.stem, len(ref), err, dur, sec))
        if err:
            print(f"{path.stem}: {show_errors(ops)}")

    print(f"\n{'File':<28}{'Số từ':>7}{'Lỗi':>6}{'WER':>8}{'Audio':>8}{'Xử lý':>8}")
    for name, words, err, dur, sec in rows:
        print(f"{name:<28}{words:>7}{err:>6}{err / words:>8.1%}{dur:>7.1f}s{sec:>7.2f}s")
    # WER tổng = tổng lỗi / tổng số từ (không lấy trung bình các %, để file ngắn không bị tính nặng như file dài).
    print(f"{'TỔNG':<28}{total_words:>7}{total_err:>6}{total_err / total_words:>8.1%}"
          f"{total_audio:>7.1f}s{total_sec:>7.2f}s")
    print(f"\nRTF (thời gian xử lý / độ dài audio): {total_sec / total_audio:.3f}")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("draft", "score"):
        print(__doc__)
        sys.exit(1)
    folder = Path(sys.argv[2])
    pattern = sys.argv[3] if len(sys.argv) > 3 else "*.wav"
    {"draft": draft, "score": score}[sys.argv[1]](folder, pattern)


if __name__ == "__main__":
    main()
