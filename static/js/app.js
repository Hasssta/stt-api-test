// Logic trang thử API: nhập key, gửi file tới /transcribe, hiện kết quả và lịch sử.
const $ = id => document.getElementById(id);

// Key giữ trong sessionStorage (mất khi đóng tab). Trình duyệt chặn storage thì vẫn chạy bình thường.
try { $("key").value = sessionStorage.getItem("stt_key") || ""; } catch (e) {}
$("key").oninput = () => { try { sessionStorage.setItem("stt_key", $("key").value.trim()); } catch (e) {} };
$("toggle").onclick = () => {
  const show = $("key").type === "password";
  $("key").type = show ? "text" : "password";
  $("toggle").textContent = show ? "Ẩn" : "Hiện";
};

// Trạng thái server
fetch("health").then(r => r.json()).then(d => {
  $("dot").className = "dot ok"; $("health").textContent = "Server đang chạy · " + d.device;
}).catch(() => {
  $("dot").className = "dot err"; $("health").textContent = "Không kết nối được server";
});

// Chọn file -> nghe lại + thông tin file
$("file").onchange = () => {
  const f = $("file").files[0];
  if (!f) return;
  $("player").src = URL.createObjectURL(f); $("player").hidden = false;
  $("fileinfo").textContent = f.name + " · " + (f.size / 1024 / 1024).toFixed(2) + " MB";
};

function countWords(s) { return s.trim() ? s.trim().split(/\s+/).length : 0; }

function addHistory(name, d, total) {
  const tr = document.createElement("tr");
  const cell = (v, cls) => {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    td.textContent = v;
    tr.appendChild(td);
    return td;
  };
  cell(new Date().toLocaleTimeString("vi-VN"));
  const fileTd = cell("", "col-file");
  const fileDiv = document.createElement("div");             // tên dài thì cắt "…", rê chuột xem đầy đủ
  fileDiv.textContent = name;
  fileTd.title = name;
  fileTd.appendChild(fileDiv);
  cell(d.audio_duration + " s");
  cell(d.processing_time + " s");
  cell(total.toFixed(2) + " s");
  cell((d.audio_duration / Math.max(d.processing_time, 0.01)).toFixed(1) + "×");
  const textTd = cell("", "col-text");
  const textDiv = document.createElement("div");
  textDiv.className = "clamp";
  textDiv.textContent = d.text || "(không nhận ra chữ nào)";
  const more = document.createElement("button");
  more.className = "more"; more.type = "button"; more.textContent = "Xem thêm"; more.hidden = true;
  more.onclick = () => {
    const open = textDiv.classList.toggle("open");
    more.textContent = open ? "Thu gọn" : "Xem thêm";
  };
  textTd.append(textDiv, more);

  $("history").prepend(tr);
  $("historyCard").hidden = false;
  // Chỉ hiện nút khi chữ thực sự dài hơn 4 dòng (đo sau khi bảng đã hiện ra)
  requestAnimationFrame(() => { more.hidden = textDiv.scrollHeight <= textDiv.clientHeight + 1; });
}

$("go").onclick = async () => {
  const f = $("file").files[0];
  const key = $("key").value.trim();
  $("status").className = "err";
  if (!key) { $("status").textContent = "Chưa nhập API key."; return; }
  if (!f) { $("status").textContent = "Chưa chọn file."; return; }

  $("go").disabled = true; $("status").className = "muted"; $("status").textContent = "Đang xử lý...";
  const t0 = performance.now();
  try {
    const fd = new FormData(); fd.append("audio", f);
    const r = await fetch("transcribe", { method: "POST", headers: { "X-API-Key": key }, body: fd });
    let d;
    try { d = await r.json(); } catch (e) { throw new Error("Lỗi " + r.status + " (server trả về dữ liệu lạ)"); }
    if (!r.ok) throw new Error("Lỗi " + r.status + ": " + (d.detail || "không rõ"));
    const total = (performance.now() - t0) / 1000;

    $("dur").textContent = d.audio_duration + " s";
    $("proc").textContent = d.processing_time + " s";
    $("total").textContent = total.toFixed(2) + " s";
    $("speed").textContent = (d.audio_duration / Math.max(d.processing_time, 0.01)).toFixed(1) + "×";
    $("words").textContent = countWords(d.text);
    $("text").textContent = d.text || "(không nhận ra chữ nào)";
    $("result").hidden = false;
    addHistory(f.name, d, total);
    $("status").className = "ok"; $("status").textContent = "Xong";
  } catch (e) {
    $("status").className = "err"; $("status").textContent = e.message;
  } finally { $("go").disabled = false; }
};

$("copy").onclick = async () => {
  try { await navigator.clipboard.writeText($("text").textContent); $("copy").textContent = "Đã chép"; }
  catch (e) { $("copy").textContent = "Không chép được"; }
  setTimeout(() => { $("copy").textContent = "Sao chép"; }, 1500);
};
$("clear").onclick = () => { $("history").innerHTML = ""; $("historyCard").hidden = true; };
