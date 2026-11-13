"""Trang web thử nghiệm: tự chọn file audio -> xem chữ PhoWhisper (faster-whisper int8, chạy CPU).

Chỉ để thử trên máy mình, chưa phải API chính (app.py vẫn giữ nguyên).

Chạy:  python bench/demo_app.py
Mở:    http://127.0.0.1:8002
"""
import io
import os
import threading
import time

import soundfile as sf
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from faster_whisper import WhisperModel

import soxr

from bench_faster_whisper import SAMPLE_RATE, split_windows   # dùng chung cách chia khung với API (stt.py)

MODEL_DIR = os.environ.get(
    "STT_MODEL_DIR", os.path.join(os.path.dirname(__file__), "..", "models", "PhoWhisper-small-int8"))
CPU_THREADS = int(os.environ.get("CPU_THREADS", "8"))   # 8 nhanh nhất trên Ryzen 6800H
MAX_BYTES = 50 * 1024 * 1024
MAX_SECONDS = 5 * 60   # trang thử nên cho dài hơn API (60s) để xem cách chia khung

print(f"Đang nạp model {MODEL_DIR} ({CPU_THREADS} luồng CPU)...", flush=True)
model = WhisperModel(MODEL_DIR, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS)
lock = threading.Lock()   # mỗi lúc chỉ xử lý 1 file

app = FastAPI(title="PhoWhisper CPU demo")


def load_audio(data: bytes):
    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float32")
    except Exception:
        raise HTTPException(400, "Không đọc được file. Hãy dùng WAV, MP3, FLAC hoặc OGG.")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SAMPLE_RATE:
        audio = soxr.resample(audio, sr, SAMPLE_RATE)
    return audio.astype("float32"), sr


@app.post("/api/transcribe")
def transcribe(audio: UploadFile = File(...)):
    data = audio.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File quá lớn (tối đa 50 MB).")

    t0 = time.perf_counter()
    wav, orig_sr = load_audio(data)
    load_s = time.perf_counter() - t0
    duration = len(wav) / SAMPLE_RATE
    if duration < 0.3:
        raise HTTPException(400, "Đoạn ghi âm quá ngắn.")
    if duration > MAX_SECONDS:
        raise HTTPException(400, f"Đoạn ghi âm quá dài (trang thử cho tối đa {MAX_SECONDS // 60} phút).")

    windows = []
    with lock:
        t_all = time.perf_counter()
        start = 0.0
        for chunk in split_windows(wav):
            t0 = time.perf_counter()
            segments, _ = model.transcribe(chunk, language="vi", task="transcribe",
                                           beam_size=1, without_timestamps=True)
            text = " ".join(s.text.strip() for s in segments).strip()
            length = len(chunk) / SAMPLE_RATE
            windows.append({"start": round(start, 2), "end": round(start + length, 2),
                            "seconds": round(time.perf_counter() - t0, 2), "text": text})
            start += length
        model_s = time.perf_counter() - t_all

    print(f"[DEMO] {audio.filename}: {duration:.1f}s audio -> {model_s:.2f}s ({len(windows)} khung)", flush=True)
    return {
        "filename": audio.filename,
        "original_sample_rate": orig_sr,
        "audio_duration": round(duration, 2),
        "decode_time": round(load_s, 2),
        "processing_time": round(model_s, 2),
        "speed": round(duration / model_s, 1),
        "text": " ".join(w["text"] for w in windows).strip(),
        "windows": windows,
    }


PAGE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PhoWhisper CPU demo</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#6b7280; --line:#e5e7eb; --accent:#2563eb; --err:#b91c1c; }
  @media (prefers-color-scheme: dark) { :root { --bg:#14161a; --card:#1d2026; --text:#e6e8ec; --muted:#9aa1ad; --line:#2d313a; --accent:#60a5fa; --err:#f87171; } }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:15px/1.6 system-ui, "Segoe UI", sans-serif; }
  main { max-width:820px; margin:0 auto; padding:24px 16px 48px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:var(--muted); margin:0 0 20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; margin-bottom:16px; }
  .row { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
  button { background:var(--accent); color:#fff; border:0; border-radius:8px; padding:9px 18px; font-size:15px; cursor:pointer; }
  button:disabled { opacity:.5; cursor:wait; }
  audio { width:100%; margin-top:14px; }
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin-bottom:14px; }
  .stat { border:1px solid var(--line); border-radius:8px; padding:8px 12px; }
  .stat b { display:block; font-size:20px; }
  .stat span { color:var(--muted); font-size:13px; }
  .text { font-size:17px; white-space:pre-wrap; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:6px 8px; border-top:1px solid var(--line); vertical-align:top; }
  th { color:var(--muted); font-weight:600; }
  .err { color:var(--err); }
  .muted { color:var(--muted); }
</style></head>
<body><main>
  <h1>PhoWhisper — thử trên CPU</h1>
  <p class="sub">faster-whisper int8 · __THREADS__ luồng CPU · chạy hoàn toàn trên máy này</p>

  <div class="card">
    <div class="row">
      <input type="file" id="file" accept="audio/*,.wav,.mp3,.flac,.ogg">
      <button id="go">Nhận dạng</button>
      <span id="status" class="muted"></span>
    </div>
    <audio id="player" controls hidden></audio>
  </div>

  <div id="result" hidden>
    <div class="card">
      <div class="stats">
        <div class="stat"><b id="dur"></b><span>độ dài audio</span></div>
        <div class="stat"><b id="proc"></b><span>thời gian model chạy</span></div>
        <div class="stat"><b id="speed"></b><span>nhanh hơn thời gian thực</span></div>
        <div class="stat"><b id="nwin"></b><span>số khung 30 giây</span></div>
      </div>
      <div class="text" id="text"></div>
    </div>
    <div class="card">
      <b>Chữ theo từng khung</b> <span class="muted">— xem chỗ nối giữa các khung có bị mất hoặc sai chữ không</span>
      <table><thead><tr><th>Đoạn</th><th>Thời gian chạy</th><th>Chữ</th></tr></thead><tbody id="wins"></tbody></table>
    </div>
  </div>
</main>
<script>
const $ = id => document.getElementById(id);
$("file").onchange = () => {
  const f = $("file").files[0];
  if (f) { $("player").src = URL.createObjectURL(f); $("player").hidden = false; }
};
$("go").onclick = async () => {
  const f = $("file").files[0];
  if (!f) { $("status").textContent = "Chưa chọn file."; return; }
  $("go").disabled = true; $("status").className = "muted"; $("status").textContent = "Đang xử lý...";
  const t0 = performance.now();
  try {
    const fd = new FormData(); fd.append("audio", f);
    const r = await fetch("/api/transcribe", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || ("Lỗi " + r.status));
    $("dur").textContent = d.audio_duration + " s";
    $("proc").textContent = d.processing_time + " s";
    $("speed").textContent = d.speed + "×";
    $("nwin").textContent = d.windows.length;
    $("text").textContent = d.text || "(không nhận ra chữ nào)";
    $("wins").innerHTML = "";
    for (const w of d.windows) {
      const tr = document.createElement("tr");
      for (const v of [w.start + "s – " + w.end + "s", w.seconds + " s", w.text]) {
        const td = document.createElement("td"); td.textContent = v; tr.appendChild(td);
      }
      $("wins").appendChild(tr);
    }
    $("result").hidden = false;
    $("status").textContent = "Xong (tổng cả gửi file: " + ((performance.now() - t0) / 1000).toFixed(2) + " s)";
  } catch (e) {
    $("status").className = "err"; $("status").textContent = e.message;
  } finally { $("go").disabled = false; }
};
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE.replace("__THREADS__", str(CPU_THREADS))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002)
