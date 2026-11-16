// Thu âm từ mic rồi đổi sang WAV 16 kHz mono.
//
// Vì sao phải đổi: trình duyệt thu ra WebM/Opus (Chrome, Edge, Firefox) hoặc MP4 (Safari),
// server không đọc được. WAV 16 kHz mono đọc được ngay, đúng tần số model cần, lại nhẹ (~1,9 MB/phút).
//
// Dùng lại ở web khác: chép file này rồi gọi
//   const rec = new WavRecorder();
//   await rec.start();             // trình duyệt hỏi quyền dùng mic
//   const wav = await rec.stop();  // Blob "audio/wav", gửi lên /transcribe ở trường "audio"
// Trình duyệt chỉ cho dùng mic trên trang https hoặc http://localhost.

class WavRecorder {
  constructor(sampleRate = 16000) {
    this.sampleRate = sampleRate;
    this.stream = null;
    this.recorder = null;
    this.chunks = [];
  }

  get recording() { return this.recorder !== null; }

  async start() {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      throw new Error("Trình duyệt không hỗ trợ thu âm (cần trang https hoặc localhost).");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = e => { if (e.data.size) this.chunks.push(e.data); };
    this.recorder.start();
  }

  // Dừng thu, trả về Blob WAV.
  async stop() {
    if (!this.recorder) throw new Error("Chưa bắt đầu thu.");
    const stopped = new Promise(resolve => { this.recorder.onstop = resolve; });
    this.recorder.stop();
    await stopped;
    const raw = new Blob(this.chunks, { type: this.recorder.mimeType });
    this._release();
    return this.toWav(raw);
  }

  // Bỏ bản đang thu (vd khi người dùng rời trang).
  cancel() {
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    this._release();
  }

  _release() {
    if (this.stream) this.stream.getTracks().forEach(t => t.stop());   // tắt mic, đèn báo mic tắt theo
    this.stream = null;
    this.recorder = null;
  }

  // Giải mã bản thu (WebM/MP4/...) -> đổi về sampleRate, trộn về 1 kênh -> đóng gói WAV 16-bit.
  async toWav(blob) {
    const ctx = new AudioContext();
    let decoded;
    try {
      decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    } finally {
      ctx.close();
    }
    const length = Math.max(1, Math.ceil(decoded.duration * this.sampleRate));
    const offline = new OfflineAudioContext(1, length, this.sampleRate);   // 1 kênh: stereo tự trộn về mono
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    const pcm = (await offline.startRendering()).getChannelData(0);
    return encodeWav(pcm, this.sampleRate);
  }
}

// Float32 [-1, 1] -> file WAV PCM 16-bit mono.
function encodeWav(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const text = (offset, s) => { for (let i = 0; i < s.length; i++) v.setUint8(offset + i, s.charCodeAt(i)); };
  text(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  v.setUint32(16, 16, true);              // độ dài phần fmt
  v.setUint16(20, 1, true);               // PCM
  v.setUint16(22, 1, true);               // 1 kênh
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);  // byte mỗi giây
  v.setUint16(32, 2, true);               // byte mỗi mẫu
  v.setUint16(34, 16, true);              // 16 bit
  text(36, "data");
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}
