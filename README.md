# STT API test: PhoWhisper chạy thuần CPU

API chuyển giọng nói tiếng Việt thành chữ, dùng model [vinai/PhoWhisper-small](https://huggingface.co/vinai/PhoWhisper-small) chạy bằng **faster-whisper (CTranslate2, int8)**. Không cần GPU.

- Tốc độ đo trên AMD Ryzen 7 6800H, 8 luồng: khoảng **2,2–3,4 giây** cho 30 giây audio.
- Chỉ trả chữ, không trả mốc thời gian (timestamp của PhoWhisper bị hỏng).
- Mỗi lúc xử lý **một** yêu cầu; nhiều người gửi cùng lúc thì xếp hàng. Hàng đợi đầy thì trả lỗi **503** ngay.

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

**Cấp key cho người khác:** mỗi người một key riêng, tạo bằng cùng lệnh trên, khai báo trong `.env`:

```
STT_API_KEYS=ban_a:key_cua_ban_a,ban_b:key_cua_ban_b
```

- Tên (`ban_a`) chỉ để ghi log: mỗi yêu cầu in ra dạng `[ban_a] 30.0s audio, xử lý 2.4s`.
- Thu hồi quyền của ai: xóa mục của người đó rồi khởi động lại server. Key của người khác không bị ảnh hưởng.
- Gửi key qua kênh riêng (tin nhắn riêng), không dán vào nhóm chung hay vào code.

## 5. Chạy server

```powershell
uvicorn app:app --host 127.0.0.1 --port 8000
```

Khi thấy dòng `Đã nạp PhoWhisper trên cpu (...) ...` là server đã sẵn sàng.

- `--host 127.0.0.1`: chỉ máy mình gọi được.
- `--host 0.0.0.0`: các máy khác trong mạng LAN cũng gọi được. Chỉ dùng khi cần.

## 6. Dùng thử

**Trang web:** mở http://127.0.0.1:8000, nhập key, chọn file audio (hoặc bấm **● Thu âm**, nói, bấm **■ Dừng**), bấm gửi.

Thu âm: trình duyệt thu ra WebM/MP4, file [static/js/recorder.js](static/js/recorder.js) đổi sang **WAV 16 kHz mono** ngay trên trình duyệt rồi mới gửi, server không phải sửa gì. Mic chỉ bật được trên `http://localhost`/`127.0.0.1` hoặc trang `https` (ví dụ địa chỉ Cloudflare Tunnel), không bật được qua `http://<IP LAN>`. Web khác muốn có nút thu âm thì chép file này, cách dùng ghi ở đầu file.

**Dòng lệnh** (máy khác cần cài `pip install requests`):

```powershell
$env:STT_API_KEY = "key-cua-ban"
python client_example.py http://127.0.0.1:8000 duong_dan\file.wav
```

**Tài liệu API tự sinh:** http://127.0.0.1:8000/docs

### Lệnh nhanh (script có sẵn)

Mở 2 cửa sổ PowerShell, cả hai đều `cd D:\Hasssta_Project\STT_API_test`:

| Cửa sổ | Lệnh | Việc |
|---|---|---|
| 1 | `.\scripts\run_server.ps1` | Bật server ở `http://127.0.0.1:8000` (không cần activate `.venv`) |
| 2 | `.\scripts\run_tunnel.ps1` | Mở tunnel, in địa chỉ công khai màu xanh và tự chép vào clipboard |

Đổi cổng: thêm `-Port 8001` vào **cả hai** lệnh. Ctrl+C ở cửa sổ nào thì tắt cái đó.

### Cho người ở nơi khác gọi (Cloudflare Tunnel)

Tạo một địa chỉ `https://...trycloudflare.com` trỏ về server trên máy mình. Không cần mở cổng modem, không lộ IP nhà, không cần tài khoản Cloudflare.

1. Tải `cloudflared-windows-amd64.exe` từ [trang phát hành chính thức](https://github.com/cloudflare/cloudflared/releases/latest), đổi tên thành `cloudflared.exe`, để ở ổ D (ví dụ `D:\Hasssta_Project\_cache\cloudflared\`).
2. Bật server như mục 5 (giữ `--host 127.0.0.1`, tunnel chạy trên cùng máy).
3. Mở cửa sổ khác, chạy:
   ```powershell
   D:\Hasssta_Project\_cache\cloudflared\cloudflared.exe tunnel --no-autoupdate --url http://127.0.0.1:8000
   ```
   Tìm dòng có `https://<chuoi-ngau-nhien>.trycloudflare.com`: đó là địa chỉ gửi cho người dùng.
4. Cấp key riêng cho người đó (mục 4, `STT_API_KEYS`), gửi qua tin nhắn riêng.

Lưu ý:
- Chỉ dùng được khi máy **bật, không ngủ**, server và tunnel đều đang chạy. Ctrl+C ở cửa sổ tunnel là ngắt truy cập từ ngoài.
- **Mỗi lần chạy lại tunnel, địa chỉ đổi**, phải gửi lại. Muốn địa chỉ cố định cần tài khoản Cloudflare và tên miền riêng.
- Cloudflare cắt yêu cầu chờ quá khoảng 100 giây. Với giới hạn mặc định 5 phút audio (xử lý khoảng 30 giây) vẫn ổn.

## 7. Các endpoint

| Đường dẫn | Cần key? | Mô tả |
|---|---|---|
| `GET /` | Không | Trang web thử API |
| `GET /health` | Không | Trả `{"status": "ok", "device": "cpu (8 luồng, int8)", "in_queue": 0, "max_queue": 4}` |
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
| 503 | Server đang bận (hàng đợi đầy). Có header `Retry-After: 5`, gửi lại sau vài giây |

`in_queue` trong `/health` là số yêu cầu đang ở trong server (đang xử lý + đang chờ).

### Hàng đợi

Model xử lý một yêu cầu mỗi lúc. Server nhận tối đa **1 đang xử lý + `STT_MAX_QUEUE` đang chờ** (mặc định 1 + 4). Yêu cầu tiếp theo bị từ chối ngay bằng lỗi 503, thay vì phải chờ rất lâu rồi hết thời gian.

Chọn `STT_MAX_QUEUE` theo độ dài audio và thời gian người dùng chịu chờ:

> thời gian chờ tối đa ≈ (`STT_MAX_QUEUE` + 1) × thời gian xử lý một file

Ví dụ trên Ryzen 7 6800H: file 30 giây xử lý khoảng 3 giây, với mặc định 4 thì người cuối hàng chờ khoảng 15 giây. File 5 phút xử lý khoảng 30 giây, khi đó nên giảm `STT_MAX_QUEUE`.

Định dạng nhận: **WAV, FLAC, OGG, MP3**. Stereo và tần số mẫu khác 16 kHz được tự chuyển đổi. Nên gửi MP3 cho nhẹ: WAV 48 kHz stereo nặng khoảng 11,5 MB/phút, MP3 khoảng 1 MB/phút.

## 8. Biến môi trường

Đặt trong `.env` hoặc trên máy. Biến đặt sẵn trên máy được ưu tiên hơn `.env`.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `STT_API_KEY` | *(bắt buộc)* | API key của chủ server, ít nhất 16 ký tự |
| `STT_API_KEYS` | *(trống)* | Key cấp cho người khác, dạng `ten:key,ten2:key2` |
| `STT_MODEL_DIR` | `models/PhoWhisper-small-int8` | Thư mục model đã chuyển đổi |
| `STT_CPU_THREADS` | số luồng logic / 2 | Số luồng CPU cho model |
| `STT_MAX_SECONDS` | `300` | Độ dài audio tối đa (giây) |
| `STT_MAX_MB` | `60` | Dung lượng file tối đa (MB) |
| `STT_MAX_QUEUE` | `4` | Số yêu cầu được chờ ngoài yêu cầu đang xử lý; vượt quá thì trả 503 |

Chọn `STT_CPU_THREADS`: đo bằng `bench/bench_faster_whisper.py`. Trên Ryzen 7 6800H (8 nhân / 16 luồng), 8 luồng nhanh nhất.

## 9. Công cụ đo và thử

```powershell
# Đo tốc độ với nhiều mức số luồng (mỗi mức chạy 3 lần)
python bench/bench_faster_whisper.py duong_dan\file.wav models\PhoWhisper-small-int8 4 8 16

# Trang thử hiện chữ từng khung 30 giây, mở http://127.0.0.1:8002
python bench/demo_app.py

# Đo độ chính xác (WER):
#   1) tạo bản nháp .txt cạnh mỗi file audio (không ghi đè file .txt đã có)
python bench/wer.py draft D:\Hasssta_Project\Audio_test "audio_*.wav"
#   2) nghe lại, sửa từng file .txt cho đúng từng chữ
#   3) so chữ model với bản chuẩn, in lỗi từng file và WER tổng
python bench/wer.py score D:\Hasssta_Project\Audio_test "audio_*.wav"
```

### Test tải (Locust)

```powershell
pip install -r requirements-loadtest.txt

# Tạo bộ audio độ dài cố định: loadtest/audio/test_10s.wav, test_30s.wav, test_60s.wav
python loadtest/make_audio.py D:\Hasssta_Project\Audio_test\VietComs1min.wav

# Bật server ở một cửa sổ khác, rồi chạy: 10 người, file 30 giây, 3 phút, lưu CSV vào loadtest/results/
$env:LOADTEST_LENGTH = "30"
locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 --headless `
    -u 10 -r 2 -t 3m --csv loadtest/results/u10_30s
```

Ghi log CPU / RAM / hàng đợi của server, mỗi giây một dòng. Chạy ở cửa sổ thứ ba, **trên cùng máy với server**, bật trước khi chạy Locust:

```powershell
python loadtest/monitor.py --url http://127.0.0.1:8000 --out loadtest/results/u10_30s_monitor.csv
```

Bấm Ctrl+C để dừng (hoặc thêm `--duration 200`). Khi dừng, script in tóm tắt CPU trung bình / cao nhất, RAM cao nhất và hàng đợi dài nhất. Cột `cpu_server_pct` tính trên cả máy: 100% là dùng hết mọi luồng logic.

**Chọn audio gửi đi:** ô **Audio** trên giao diện web (hoặc `--audio` khi chạy dòng lệnh) nhận:
- đường dẫn một **file** (WAV/MP3/FLAC/OGG): mọi yêu cầu gửi file đó;
- đường dẫn một **thư mục**: mỗi yêu cầu chọn ngẫu nhiên một file trong thư mục;
- để mặc định: `loadtest/audio/test_<LOADTEST_LENGTH>s.wav`.

Kết quả được thống kê riêng theo từng tên file.

Mỗi người dùng ảo gửi một file, chờ kết quả, nghỉ 1–2 giây rồi gửi tiếp. Lỗi 503 (server bận) và 401 (sai key) được ghi riêng trong kết quả. Bỏ `--headless` để xem biểu đồ trực tiếp ở http://localhost:8089.

## 10. Cách xử lý audio dài

Whisper xử lý theo khung 30 giây. Audio dài hơn được chia thành nhiều khung, **cắt ở giữa khoảng lặng dài nhất trong 5 giây cuối** mỗi khung (thường là chỗ hết câu), để không cắt ngang từ. Phần dư cuối ngắn hơn hoặc bằng 0,5 giây thì bỏ, vì khung gần như rỗng làm model "bịa" chữ.

Cấu hình nhận dạng cố định trong `stt.py`: `language="vi"`, `beam_size=1`, `without_timestamps=True`.

## 11. Giới hạn đã biết

- PhoWhisper gần như không nhận tiếng Anh. Từ tiếng Anh chèn trong câu tiếng Việt có thể bị sai (ví dụ "gym" thành "di").
- Trên Windows, nếu chuyển log của server vào file (`uvicorn ... > server.log`) thì server lỗi khi in chữ tiếng Việt. Đặt `$env:PYTHONUTF8 = "1"` trước khi chạy.

## 12. Cấu trúc thư mục

```
app.py                  API FastAPI (/, /health, /transcribe, /static/...)
stt.py                  nạp model, chia khung 30 giây, nhận dạng
client_example.py       ví dụ gọi API bằng Python
static/
  index.html            trang thử API (chỉ có khung HTML)
  css/style.css         giao diện
  js/app.js             logic trang: gửi file, hiện kết quả, lịch sử
  js/recorder.js        thu âm từ mic -> WAV 16 kHz mono (dùng lại được ở web khác)
scripts/                run_server.ps1, run_tunnel.ps1: lệnh chạy nhanh
bench/                  đo tốc độ, đo WER, trang demo từng khung
loadtest/               test tải: Locust, tạo audio, ghi log CPU/RAM
  audio/, results/      file sinh ra khi chạy (không đưa lên Git)
models/                 model đã chuyển đổi (không đưa lên Git)
```

## Chạy trên Linux

Các bước giống hệt, chỉ khác cú pháp lệnh:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Lệnh chuyển đổi model: thay dấu ` cuối dòng bằng dấu \
```
