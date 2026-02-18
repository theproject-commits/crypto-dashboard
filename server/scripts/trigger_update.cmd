@echo off
set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%trigger_update.ps1" -ApiBase "http://127.0.0.1:8000" -Username "admincel" -Password "8523"
