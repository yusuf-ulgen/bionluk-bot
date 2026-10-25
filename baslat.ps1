# Bionluk İlan Takipçisi PowerShell Başlatıcı
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "       Bionluk İlan & Alıcı İstekleri Takipçisi" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$PythonExe = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "[HATA] Sanal ortam ($PythonExe) bulunamadı!" -ForegroundColor Red
    Write-Host "Lütfen önce ortamı hazırlayın:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\pip install -r requirements.txt"
    Write-Host "  .venv\Scripts\playwright install chromium"
    Read-Host "Devam etmek için Enter tuşuna basın..."
    exit 1
}

Write-Host "Uygulama başlatılıyor..." -ForegroundColor Yellow
try {
    & $PythonExe (Join-Path $ScriptDir "main.py")
}
catch {
    Write-Host "[HATA] Uygulama çalıştırılamadı: $_" -ForegroundColor Red
}
finally {
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
        Write-Host ""
        Write-Host "[BİLGİ] Uygulama hata kodu ile kapandı: $LASTEXITCODE" -ForegroundColor Yellow
        Write-Host "Detaylar için 'data\logs\bot.log' dosyasını inceleyin."
        Read-Host "Pencereyi kapatmak için Enter tuşuna basın..."
    }
}
