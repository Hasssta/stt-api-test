# STT API test: PhoWhisper chạy thuần CPU

API chuyển giọng nói tiếng Việt thành chữ, dùng model [vinai/PhoWhisper-small](https://huggingface.co/vinai/PhoWhisper-small) chạy bằng **faster-whisper (CTranslate2, int8)**. Không cần GPU.

- Tốc độ đo trên AMD Ryzen 7 6800H, 8 luồng: khoảng **2,2–3,4 giây** cho 30 giây audio.
- Chỉ trả chữ, không trả mốc thời gian (timestamp của PhoWhisper bị hỏng).
- Mỗi lúc xử lý **một** yêu cầu; nhiều người gửi cùng lúc thì xếp hàng.

> Hướng dẫn dưới đây viết cho **Windows + PowerShell** (máy cá nhân). Trên Linux, xem mục [Chạy trên Linux](#chạy-trên-linux).

---

## 1. Yêu cầu

- Python **3.10 trở lên** (đã chạy với 3.13).
- Khoảng **1 GB** ổ cứng trống cho lúc chuyển đổi model (tải model gốc ~1 GB, model int8 sau chuyển đổi ~250 MB).
- RAM: từ 4 GB trở lên là đủ cho một tiến trình.

## 2. Cài đặt

```powershell
cd D:\Hasssta_Project\STT_API_test
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Nếu PowerShell báo không cho chạy script, mở PowerShell rồi chạy một lần:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## 3. Chuyển đổi model (làm một lần)

API cần model ở định dạng CTranslate2 int8. Việc chuyển đổi cần thêm torch và transformers. Chỉ cần làm một lần, sau đó có thể gỡ hai gói này.

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-convert.txt

ct2-transformers-converter --model vinai/PhoWhisper-small `
    --output_dir models/PhoWhisper-small-int8 `
    --quantization int8 --copy_files tokenizer.json preprocessor_config.json
```

Kết quả là thư mục `models/PhoWhisper-small-int8/` chứa `model.bin`, `config.json`, `tokenizer.json`, `preprocessor_config.json`, `vocabulary.json`. Thư mục `models/` **không được đưa lên Git**.

> Mẹo: model gốc được tải vào cache HuggingFace, mặc định nằm ở ổ C. Muốn để ở ổ khác thì đặt trước khi chuyển đổi:
> `$env:HF_HOME = "D:\Hasssta_Project\_cache\huggingface"`

Gỡ gói chuyển đổi (không bắt buộc):

```powershell
pip uninstall -y torch transformers
```

## 4. Tạo API key

Key là bí mật, **chỉ để trong file `.env`**. File này đã nằm trong `.gitignore`, không được commit.

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Mở `.env`, dán chuỗi vừa in ra vào sau `STT_API_KEY=`. Key phải dài **ít nhất 16 ký tự**, nếu không server sẽ không khởi động.

## 5. Chạy server

```powershell
uvicorn app:app --host 127.0.0.1 --port 8000
```

Khi thấy dòng `Đã nạp PhoWhisper trên cpu (...) ...` là server đã sẵn sàng.

- `--host 127.0.0.1`: chỉ máy mình gọi được.
- `--host 0.0.0.0`: các máy khác trong mạng LAN cũng gọi được. Chỉ dùng khi cần.

## 6. Dùng thử

**Trang web:** mở http://127.0.0.1:8000, nhập key, chọn file audio, bấm gửi.

**Dòng lệnh** (máy khác cần cài `pip install requests`):

```powershell
$env:STT_API_KEY = "key-cua-ban"
python client_example.py http://127.0.0.1:8000 duong_dan\file.wav
```

**Tài liệu API tự sinh:** http://127.0.0.1:8000/docs

## 7. Các endpoint

| Đường dẫn | Cần key? | Mô tả |
|---|---|---|
| `GET /` | Không | Trang web thử API |
| `GET /health` | Không | Trả `{"status": "ok", "device": "cpu (8 luồng, int8)"}` |
| `POST /transcribe` | **Có**, header `X-API-Key` | Gửi file audio ở trường `audio` (multipart/form-data) |

Ví dụ kết quả `POST /transcribe`:

```json
{ "text": "xin chào ...", "audio_duration": 30.0, "processing_time": 2.41 }
```

| Mã lỗi | Khi nào |
|---|---|
| 400 | Không đọc được file, audio ngắn hơn 0,3 giây hoặc dài hơn giới hạn |
| 401 | Thiếu hoặc sai API key |
| 413 | File vượt dung lượng tối đa |

Định dạng nhận: **WAV, FLAC, OGG, MP3**. Stereo và tần số mẫu khác 16 kHz được tự chuyển đổi. Nên gửi MP3 cho nhẹ: WAV 48 kHz stereo nặng khoảng 11,5 MB/phút, MP3 khoảng 1 MB/phút.

## 8. Biến môi trường

Đặt trong `.env` hoặc trên máy. Biến đặt sẵn trên máy được ưu tiên hơn `.env`.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `STT_API_KEY` | *(bắt buộc)* | API key, ít nhất 16 ký tự |
| `STT_MODEL_DIR` | `models/PhoWhisper-small-int8` | Thư mục model đã chuyển đổi |
| `STT_CPU_THREADS` | số luồng logic / 2 | Số luồng CPU cho model |
| `STT_MAX_SECONDS` | `300` | Độ dài audio tối đa (giây) |
| `STT_MAX_MB` | `60` | Dung lượng file tối đa (MB) |

Chọn `STT_CPU_THREADS`: đo bằng `bench/bench_faster_whisper.py`. Trên Ryzen 7 6800H (8 nhân / 16 luồng), 8 luồng nhanh nhất.

## 9. Công cụ đo và thử

```powershell
# Đo tốc độ với nhiều mức số luồng (mỗi mức chạy 3 lần)
python bench/bench_faster_whisper.py duong_dan\file.wav models\PhoWhisper-small-int8 4 8 16

# Trang thử hiện chữ từng khung 30 giây, mở http://127.0.0.1:8002
python bench/demo_app.py
```

## 10. Cách xử lý audio dài

Whisper xử lý theo khung 30 giây. Audio dài hơn được chia thành nhiều khung, **cắt ở giữa khoảng lặng dài nhất trong 5 giây cuối** mỗi khung (thường là chỗ hết câu), để không cắt ngang từ. Phần dư cuối ngắn hơn hoặc bằng 0,5 giây thì bỏ, vì khung gần như rỗng làm model "bịa" chữ.

Cấu hình nhận dạng cố định trong `stt.py`: `language="vi"`, `beam_size=1`, `without_timestamps=True`.

## 11. Giới hạn đã biết

- PhoWhisper gần như không nhận tiếng Anh. Từ tiếng Anh chèn trong câu tiếng Việt có thể bị sai (ví dụ "gym" thành "di").
- Chưa có hàng đợi giới hạn: khi quá tải, yêu cầu sẽ chờ thay vì bị từ chối ngay.

## Chạy trên Linux

Các bước giống hệt, chỉ khác cú pháp lệnh:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Lệnh chuyển đổi model: thay dấu ` cuối dòng bằng dấu \
```
