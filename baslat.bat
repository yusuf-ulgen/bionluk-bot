@echo off
setlocal
cd /d "%~dp0"
title Bionluk Ilan Takipcisi

echo ========================================================
echo        Bionluk Ilan ve Alici Istekleri Takipcisi
echo ========================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [HATA] Sanal ortam ^(.venv^) bulunamadi!
    echo Lutfen once asagidaki komutlarla ortami olusturun:
    echo    python -m venv .venv
    echo    .venv\Scripts\pip install -r requirements.txt
    echo    .venv\Scripts\playwright install chromium
    echo.
    pause
    exit /b 1
)

echo Uygulama baslatiliyor, lutfen bekleyin...
.venv\Scripts\python.exe main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [BILGI] Uygulama bir hata ile sonlandi (Hata Kodu: %ERRORLEVEL%).
    echo Ayrintilar icin data\logs\bot.log dosyasini inceleyebilirsiniz.
    echo.
    pause
)
