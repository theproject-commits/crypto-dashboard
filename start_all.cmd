@echo off
setlocal

set "ROOT=%~dp0"
set "MODE=%~1"
if /I "%MODE%"=="" set "MODE=dev"
set "FRONTEND_PORT=5173"

echo [TentacleLab] Root: %ROOT%
echo [TentacleLab] Mode: %MODE%

call :kill_port 8000
call :kill_port %FRONTEND_PORT%

echo [TentacleLab] Starting backend on 127.0.0.1:8000...
start "TentacleLab Backend" cmd /k "cd /d %ROOT% && python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --app-dir server"

if /I "%MODE%"=="dist" (
  echo [TentacleLab] Starting frontend DIST on 127.0.0.1:%FRONTEND_PORT%...
  start "TentacleLab Frontend (dist)" cmd /k "cd /d %ROOT% && python -m http.server %FRONTEND_PORT% --directory client/dist --bind 127.0.0.1"
) else (
  echo [TentacleLab] Starting frontend DEV on 127.0.0.1:%FRONTEND_PORT%...
  start "TentacleLab Frontend (dev)" cmd /k "cd /d %ROOT% && npm run dev --prefix client -- --host 127.0.0.1 --port %FRONTEND_PORT%"
)

echo.
echo [TentacleLab] Open:
echo   Frontend: http://127.0.0.1:%FRONTEND_PORT%
echo   Backend : http://127.0.0.1:8000/docs
echo.
echo [TentacleLab] Tip: use "start_all.cmd dist" to serve client/dist.
goto :eof

:kill_port
set "PORT=%~1"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  echo [TentacleLab] Killing PID %%P on port %PORT%...
  taskkill /PID %%P /F >nul 2>nul
)
goto :eof
