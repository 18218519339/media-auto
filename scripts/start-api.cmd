@echo off
setlocal
cd /d "%~dp0..\apps\api-server"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
