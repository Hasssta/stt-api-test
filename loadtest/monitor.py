"""Ghi log tài nguyên của server STT trong lúc test tải: mỗi giây một dòng CSV.

Ghi lại:
  cpu_total_pct  % CPU của CẢ MÁY (0–100)
  cpu_server_pct % CPU do server dùng, tính trên cả máy (0–100). 100 = dùng hết mọi luồng logic.
  cores_used     số luồng logic server đang dùng (vd 7.8 = gần 8 luồng chạy hết công suất)
  ram_server_mb  RAM server đang chiếm (RSS, cộng cả tiến trình con nếu chạy nhiều worker)
  ram_total_pct  % RAM của cả máy đang dùng
  in_queue       số request đang trong server (đang xử lý + đang chờ), đọc từ /health

Chạy (mở một cửa sổ riêng, bật TRƯỚC khi chạy Locust, Ctrl+C để dừng):
  python loadtest/monitor.py --url http://127.0.0.1:8000 --out loadtest/results/u10_30s_monitor.csv
Tùy chọn:
  --pid 1234      chỉ định tiến trình server (mặc định: tự tìm tiến trình đang nghe ở cổng trong --url)
  --duration 180  tự dừng sau 180 giây
  --interval 1    số giây giữa 2 lần đo
"""
import argparse
import csv
import json
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import psutil

FIELDS = ["time", "elapsed_s", "cpu_total_pct", "cpu_server_pct", "cores_used",
          "ram_server_mb", "ram_total_pct", "in_queue"]


def find_server(port: int) -> psutil.Process:
    for c in psutil.net_connections(kind="tcp"):
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port and c.pid:
            return psutil.Process(c.pid)
    raise SystemExit(f"Không thấy tiến trình nào đang nghe ở cổng {port}. Server đã chạy chưa? (hoặc dùng --pid)")


def server_processes(main: psutil.Process) -> list[psutil.Process]:
    # Gồm cả tiến trình con: khi chạy uvicorn --workers N, mỗi worker là một tiến trình con.
    try:
        return [main] + main.children(recursive=True)
    except psutil.NoSuchProcess:
        return []


def read_queue(url: str):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=2) as r:
            return json.load(r).get("in_queue", "")
    except Exception:
        return ""   # server bận quá không trả lời kịp -> để trống, không dừng việc ghi log


def main():
    ap = argparse.ArgumentParser(description="Ghi log CPU/RAM/hàng đợi của server STT.")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--out", default="loadtest/results/monitor.csv")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--duration", type=float)
    args = ap.parse_args()

    main_proc = psutil.Process(args.pid) if args.pid else find_server(urlparse(args.url).port or 80)
    n_cpu = psutil.cpu_count(logical=True)
    print(f"Theo dõi tiến trình {main_proc.pid} ({main_proc.name()}), máy có {n_cpu} luồng logic.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Lần gọi cpu_percent đầu tiên luôn trả 0 -> gọi "mồi" một lần, các lần sau mới có số đúng.
    procs = {p.pid: p for p in server_processes(main_proc)}
    for p in procs.values():
        p.cpu_percent(None)
    psutil.cpu_percent(None)

    rows = []
    start = time.time()
    print(f"Đang ghi vào {out} (Ctrl+C để dừng)...")
    try:
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            while args.duration is None or time.time() - start < args.duration:
                time.sleep(args.interval)
                # Cập nhật danh sách tiến trình (worker có thể khởi động lại); tiến trình mới thì mồi cpu_percent.
                for p in server_processes(main_proc):
                    if p.pid not in procs:
                        procs[p.pid] = p
                        p.cpu_percent(None)
                cpu_sum, rss = 0.0, 0
                for pid, p in list(procs.items()):
                    try:
                        cpu_sum += p.cpu_percent(None)   # % của MỘT luồng, có thể > 100
                        rss += p.memory_info().rss
                    except psutil.NoSuchProcess:
                        del procs[pid]
                if not procs:
                    print("Server đã tắt, dừng ghi.")
                    break
                row = {
                    "time": time.strftime("%H:%M:%S"),
                    "elapsed_s": round(time.time() - start, 1),
                    "cpu_total_pct": psutil.cpu_percent(None),
                    "cpu_server_pct": round(cpu_sum / n_cpu, 1),
                    "cores_used": round(cpu_sum / 100, 2),
                    "ram_server_mb": round(rss / 1024 / 1024),
                    "ram_total_pct": psutil.virtual_memory().percent,
                    "in_queue": read_queue(args.url),
                }
                w.writerow(row)
                f.flush()   # ghi ngay, lỡ bị tắt ngang vẫn còn dữ liệu
                rows.append(row)
    except KeyboardInterrupt:
        pass

    if rows:
        cpu = [r["cpu_server_pct"] for r in rows]
        cores = [r["cores_used"] for r in rows]
        ram = [r["ram_server_mb"] for r in rows]
        queue = [r["in_queue"] for r in rows if r["in_queue"] != ""]
        print(f"\n{len(rows)} lần đo trong {rows[-1]['elapsed_s']}s")
        print(f"CPU server : trung bình {sum(cpu) / len(cpu):.1f}%, cao nhất {max(cpu):.1f}% "
              f"(~{max(cores):.1f} luồng)")
        print(f"RAM server : cao nhất {max(ram)} MB")
        if queue:
            print(f"Hàng đợi   : cao nhất {max(queue)} request")


if __name__ == "__main__":
    main()
