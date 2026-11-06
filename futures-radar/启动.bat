@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0backend"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Please install Python 3.10+ and check "Add to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating virtual env...
  python -m venv .venv
)

echo [2/4] Installing dependencies...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed. Check network and retry.
  pause
  exit /b 1
)

echo [3/4] Downloading Cloudflare Tunnel...
set "CF_DIR=%~dp0cloudflared"
if not exist "%CF_DIR%\cloudflared.exe" (
  mkdir "%CF_DIR%" 2>nul
  powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%CF_DIR%\cloudflared.exe'" 2>nul
  if not exist "%CF_DIR%\cloudflared.exe" (
    echo [SKIP] cloudflared download failed. Local LAN only.
  )
)

echo [4/4] Starting Futures Radar backend...
start "Radar Backend" cmd /k ""%cd%\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
timeout /t 5 >nul

echo.
echo ============================================
echo   Futures Radar - Running
echo ============================================
echo.
echo Local:    http://127.0.0.1:8000
start "" http://127.0.0.1:8000

for /f %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object {$_.IPAddress -notlike ''127.*''} ^| Select-Object -First 1).IPAddress"') do set LANIP=%%i
if defined LANIP (
  echo Phone/Wi-Fi: http://%LANIP%:8000
)

if exist "%CF_DIR%\cloudflared.exe" (
  echo.
  echo --- Starting public tunnel (10-20 sec) ---
  echo Public URL will be shown below:
  start "CF Tunnel" cmd /c ""%CF_DIR%\cloudflared.exe" tunnel --url http://127.0.0.1:8000 --no-autoupdate 2>&1 | findstr /i "https://.*trycloudflare.com""
)

echo.
echo ============================================
echo   Close the "Radar Backend" window to stop.
echo ============================================
pause
