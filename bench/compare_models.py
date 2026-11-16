"""So sánh nhiều model PhoWhisper (đã chuyển đổi int8) trên cùng bộ audio, dùng ĐÚNG cách nhận dạng của API.

In ra và lưu báo cáo Markdown (bench/results/compare_<giờ>.md):
  - Bảng tốc độ: thời gian xử lý từng file với mỗi model (lấy lần nhanh nhất trong --runs lần), RAM.
  - Chữ của từng model, kèm chỗ khác nhau giữa 2 model đầu: [chữ model 1 → chữ model 2].
  - Nếu cạnh file audio có file .txt cùng tên (bản chép chuẩn, xem bench/wer.py) -> tính thêm WER mỗi model.

Chạy:
  python bench/compare_models.py <thư_mục_audio> [mẫu_tên_file] [--models small medium] [--runs 2]
Ví dụ:
  python bench/compare_models.py D:\\Hasssta_Project\\Audio_test "Keo_tren_keo_duoi*.wav"
Model "small" nghĩa là thư mục models/PhoWhisper-small-int8.
"""
import argparse
import gc
import os
import sys
import time
from pathlib import Path

import psutil
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from stt import STT  # noqa: E402
from wer import align, normalize  # noqa: E402


def run_model(name: str, files: list[Path], runs: int) -> dict:
    os.environ["STT_MODEL_DIR"] = str(ROOT / "models" / f"PhoWhisper-{name}-int8")   # STT đọc biến này lúc khởi tạo
    stt = STT()
    proc = psutil.Process()
    peak = proc.memory_info().rss
    out = {"load": stt.load_seconds, "files": {}}
    for f in files:
        wav, sr = sf.read(f, dtype="float32")
        best, text = None, ""
        for _ in range(runs):
            t = time.perf_counter()
            text = stt.transcribe(wav, sr)
            dt = time.perf_counter() - t
            best = dt if best is None else min(best, dt)
            peak = max(peak, proc.memory_info().rss)
        out["files"][f.name] = {"dur": len(wav) / sr, "time": best, "text": text}
        print(f"  [{name}] {f.name}: {best:.2f}s", flush=True)
    out["ram_mb"] = peak / 1024 / 1024
    del stt
    gc.collect()
    return out


def diff_text(a: str, b: str) -> tuple[str, int]:
    """Chữ của model b, đánh dấu chỗ khác model a. Trả (chuỗi đánh dấu, số từ khác)."""
    parts, n = [], 0
    for op, wa, wb in align(normalize(a), normalize(b)):
        if op == "ok":
            parts.append(wb)
        else:
            n += 1
            parts.append({"sub": f"**[{wa} → {wb}]**", "del": f"**[{wa} → ∅]**", "ins": f"**[∅ → {wb}]**"}[op])
    return " ".join(parts), n


def wer(ref: str, hyp: str) -> tuple[int, int]:
    r = normalize(ref)
    errors = sum(op != "ok" for op, _, _ in align(r, normalize(hyp)))
    return errors, len(r)


def short(name: str, width: int = 28) -> str:
    stem = Path(name).stem
    return stem if len(stem) <= width else "…" + stem[-(width - 1):]


def main():
    ap = argparse.ArgumentParser(description="So sánh các model PhoWhisper trên cùng bộ audio.")
    ap.add_argument("folder")
    ap.add_argument("pattern", nargs="?", default="*.wav")
    ap.add_argument("--models", nargs="+", default=["small", "medium"])
    ap.add_argument("--runs", type=int, default=2, help="số lần chạy mỗi file, lấy lần nhanh nhất")
    args = ap.parse_args()

    files = sorted(Path(args.folder).glob(args.pattern))
    if not files:
        sys.exit(f"Không thấy file nào khớp {args.pattern} trong {args.folder}")
    for m in args.models:
        if not (ROOT / "models" / f"PhoWhisper-{m}-int8").is_dir():
            sys.exit(f"Chưa có models/PhoWhisper-{m}-int8")

    print(f"{len(files)} file, model: {', '.join(args.models)}, {args.runs} lần/file")
    res = {m: run_model(m, files, args.runs) for m in args.models}
    refs = {f.name: f.with_suffix(".txt").read_text(encoding="utf-8")
            for f in files if f.with_suffix(".txt").is_file()}

    ms = args.models
    L = [f"# So sánh model: {' vs '.join(ms)}", "",
         f"- Thư mục: `{args.folder}`, mẫu `{args.pattern}`, {len(files)} file",
         f"- Máy: {psutil.cpu_count()} luồng logic, STT_CPU_THREADS={os.environ.get('STT_CPU_THREADS', 'mặc định')}; "
         f"thời gian = lần nhanh nhất trong {args.runs} lần", ""]

    # Bảng tốc độ
    L += ["## Tốc độ", "",
          "| File | Audio (s) | " + " | ".join(f"{m} (s)" for m in ms) + (f" | {ms[1]} / {ms[0]}" if len(ms) > 1 else "") + " |",
          "|---|---:|" + "---:|" * len(ms) + ("---:|" if len(ms) > 1 else "")]
    tot_dur = sum(res[ms[0]]["files"][f.name]["dur"] for f in files)
    for f in files:
        r = [res[m]["files"][f.name] for m in ms]
        row = f"| {short(f.name)} | {r[0]['dur']:.1f} | " + " | ".join(f"{x['time']:.2f}" for x in r)
        if len(ms) > 1:
            row += f" | {r[1]['time'] / r[0]['time']:.1f}×"
        L.append(row + " |")
    tots = [sum(res[m]["files"][f.name]["time"] for f in files) for m in ms]
    row = f"| **Tổng** | **{tot_dur:.1f}** | " + " | ".join(f"**{t:.2f}**" for t in tots)
    L.append(row + (f" | **{tots[1] / tots[0]:.1f}×**" if len(ms) > 1 else "") + " |")
    L += ["", "| Model | Nạp model (s) | RAM cao nhất (MB) | Nhanh hơn thời gian thực |", "|---|---:|---:|---:|"]
    for m, t in zip(ms, tots):
        L.append(f"| {m} | {res[m]['load']} | {res[m]['ram_mb']:.0f} | {tot_dur / t:.1f}× |")

    # WER nếu có bản chuẩn
    if refs:
        L += ["", f"## WER ({len(refs)} file có bản chép chuẩn .txt)", "", "| Model | Lỗi / số từ | WER |", "|---|---:|---:|"]
        for m in ms:
            e = n = 0
            for name, ref in refs.items():
                de, dn = wer(ref, res[m]["files"][name]["text"])
                e, n = e + de, n + dn
            L.append(f"| {m} | {e} / {n} | {e / max(n, 1):.1%} |")

    # Chữ từng file
    L += ["", "## Chữ nhận dạng", ""]
    if len(ms) > 1:
        L += [f"Dòng **{ms[1]}** đánh dấu chỗ khác {ms[0]}: **[chữ {ms[0]} → chữ {ms[1]}]**, ∅ là không có.", ""]
    total_diff = total_words = 0
    for f in files:
        L.append(f"### {f.name}")
        if f.name in refs:
            L.append(f"- **chuẩn:** {refs[f.name].strip()}")
        first = res[ms[0]]["files"][f.name]["text"]
        L.append(f"- **{ms[0]}:** {first}")
        for m in ms[1:]:
            marked, n = diff_text(first, res[m]["files"][f.name]["text"])
            total_diff += n
            total_words += len(normalize(first))
            L.append(f"- **{m}:** {marked}  _(khác {n} từ)_")
        L.append("")
    if len(ms) > 1:
        L.insert(L.index("## Chữ nhận dạng") + 2,
                 f"Tổng cộng {ms[1]} khác {ms[0]} ở **{total_diff}** chỗ (trên {total_words} từ của {ms[0]}).\n")

    report = "\n".join(L)
    out = ROOT / "bench" / "results" / f"compare_{time.strftime('%Y%m%d_%H%M%S')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print("\n" + report + f"\n\nĐã lưu: {out}")


if __name__ == "__main__":
    main()
