"""PhoWhisper: giọng nói -> chữ.

Nạp model MỘT lần khi server khởi động, dùng lại cho mọi request.
"""
import threading
import time

import numpy as np
import torch
from transformers import pipeline

MODEL_ID = "vinai/PhoWhisper-small"
SAMPLE_RATE = 16000   # PhoWhisper (giống Whisper) cần audio 16 kHz


class STT:
    def __init__(self, model_id: str = MODEL_ID):
        use_gpu = torch.cuda.is_available()
        self.device = torch.cuda.get_device_name(0) if use_gpu else "cpu"

        t0 = time.perf_counter()
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=model_id,
            dtype=torch.float16 if use_gpu else torch.float32,   # fp16: tốn nửa VRAM, nhanh hơn trên T4
            device=0 if use_gpu else -1,
        )
        self.load_seconds = round(time.perf_counter() - t0, 1)

        # Mỗi lúc GPU chỉ xử lý MỘT request -> nhiều người gửi cùng lúc thì xếp hàng, không bị hết VRAM.
        self._lock = threading.Lock()

    def transcribe(self, audio: np.ndarray, sr: int) -> str:
        if audio.ndim > 1:                 # stereo -> mono
            audio = audio.mean(axis=1)
        if sr != SAMPLE_RATE:              # chuyển về 16 kHz nếu file gửi lên khác
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)
        with self._lock:
            out = self.pipe(
                {"raw": audio.astype(np.float32), "sampling_rate": SAMPLE_RATE},
                chunk_length_s=30,         # cần cho đoạn dài hơn 30 giây
                batch_size=4,
            )
        return out["text"].strip()
