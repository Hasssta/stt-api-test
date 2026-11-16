# Bật server STT (chỉ máy này gọi được; người ở nơi khác gọi qua run_tunnel.ps1).
# Chạy từ thư mục STT_API_test:   .\scripts\run_server.ps1
# Đổi cổng:                      .\scripts\run_server.ps1 -Port 8001
# API key đọc từ file .env (không ghi trong script này).
param([int]$Port = 8000)

$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Không thấy .venv. Làm mục 2 (Cài đặt) trong README trước." -ForegroundColor Red
    exit 1
}

Set-Location $root
$env:PYTHONUTF8 = "1"   # để in chữ tiếng Việt không lỗi khi chuyển log ra file
Write-Host "Bật server ở http://127.0.0.1:$Port  (Ctrl+C để tắt)" -ForegroundColor Cyan
& $python -m uvicorn app:app --host 127.0.0.1 --port $Port
