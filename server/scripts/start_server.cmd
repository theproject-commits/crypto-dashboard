@echo off
cd /d C:\Users\iagor\Projects\crypto-dashboard\server
call C:\Users\iagor\Projects\crypto-dashboard\server\venv\Scripts\uvicorn.exe src.main:app --host 127.0.0.1 --port 8000 --app-dir . >> C:\Users\iagor\Projects\crypto-dashboard\server\uvicorn_bg.out.log 2>> C:\Users\iagor\Projects\crypto-dashboard\server\uvicorn_bg.err.log
