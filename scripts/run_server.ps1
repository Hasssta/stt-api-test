# Bật server STT (chỉ máy này gọi được; người ở nơi khác gọi qua run_tunnel.ps1).
# Chạy từ thư mục STT_API_test:   .\scripts\run_server.ps1
# Đổi cổng:                      .\scripts\run_server.ps1 -Port 8001
# Chọn model:                    .\scripts\run_server.ps1 -Model medium   (small | medium)
#   Không ghi -Model: dùng STT_MODEL_DIR trong .env, không có thì dùng small.
# API key đọc từ file .env (không ghi trong script này).
param(
    [int]$Port = 8000,
    [ValidateSet("small", "medium")][string]$Model
)

$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Không thấy .venv. Làm mục 2 (Cài đặt) trong README trước." -ForegroundColor Red
    exit 1
}

Set-Location $root
$oldModelDir = $env:STT_MODEL_DIR   # trả lại khi tắt, để lần chạy sau trong cùng cửa sổ không bị dính model cũ
$env:PYTHONUTF8 = "1"   # để in chữ tiếng Việt không lỗi khi chuyển log ra file
if ($Model) {
    $dir = "models\PhoWhisper-$Model-int8"
    if (-not (Test-Path (Join-Path $root $dir))) {
        Write-Host "Chưa có model $dir. Chuyển đổi theo mục 3 trong README." -ForegroundColor Red
        exit 1
    }
    $env:STT_MODEL_DIR = $dir   # biến đặt trên máy được ưu tiên hơn .env
    Write-Host "Model: PhoWhisper-$Model" -ForegroundColor Cyan
}
Write-Host "Bật server ở http://127.0.0.1:$Port  (Ctrl+C để tắt)" -ForegroundColor Cyan
try {
    & $python -m uvicorn app:app --host 127.0.0.1 --port $Port
} finally {
    $env:STT_MODEL_DIR = $oldModelDir
}
