# Mở Cloudflare Tunnel: tạo địa chỉ https://....trycloudflare.com trỏ về server trên máy này.
# Bật run_server.ps1 TRƯỚC, rồi mở cửa sổ khác chạy:   .\scripts\run_tunnel.ps1
# Địa chỉ được in màu xanh và tự chép vào clipboard. Ctrl+C để ngắt truy cập từ ngoài.
# Mỗi lần chạy lại, địa chỉ ĐỔI -> phải gửi lại cho người dùng.
#
# cloudflared.exe mặc định ở  <thư mục cha của project>\_cache\cloudflared\cloudflared.exe
# Để chỗ khác thì đặt biến:   $env:CLOUDFLARED = "D:\duong_dan\cloudflared.exe"
param([int]$Port = 8000)

$root = Split-Path $PSScriptRoot -Parent
$exe = if ($env:CLOUDFLARED) { $env:CLOUDFLARED } else { Join-Path (Split-Path $root -Parent) "_cache\cloudflared\cloudflared.exe" }
if (-not (Test-Path $exe)) {
    Write-Host "Không thấy cloudflared ở: $exe" -ForegroundColor Red
    Write-Host "Tải từ https://github.com/cloudflare/cloudflared/releases/latest (cloudflared-windows-amd64.exe)."
    exit 1
}

try {
    Invoke-WebRequest "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
    Write-Host "Server chưa chạy ở cổng $Port. Bật .\scripts\run_server.ps1 ở cửa sổ khác trước." -ForegroundColor Red
    exit 1
}

Write-Host "Đang mở tunnel tới http://127.0.0.1:$Port ... (Ctrl+C để tắt)" -ForegroundColor Cyan
$shown = $false
# cloudflared in log ra stderr -> gộp vào để lọc lấy địa chỉ.
& $exe tunnel --no-autoupdate --url "http://127.0.0.1:$Port" 2>&1 | ForEach-Object {
    $line = "$_"
    if (-not $shown -and $line -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
        $shown = $true
        $url = $Matches[0]
        try { Set-Clipboard -Value $url } catch {}
        Write-Host ""
        Write-Host "  ĐỊA CHỈ CÔNG KHAI: $url" -ForegroundColor Green
        Write-Host "  (đã chép vào clipboard; gửi kèm key riêng cho người dùng)" -ForegroundColor Green
        Write-Host "  Tài liệu API:      $url/docs" -ForegroundColor Green
        Write-Host "  Địa chỉ mới cần khoảng 30-60 giây mới gọi được, lỗi lúc đầu là bình thường." -ForegroundColor Green
        Write-Host ""
    } elseif ($line -match ' ERR ') {
        Write-Host $line -ForegroundColor Yellow
    }
}
