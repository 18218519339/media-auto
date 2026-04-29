@echo off
setlocal
cd /d "%~dp0..\apps\admin-web"
npm.cmd run build
python -m http.server 5173 --bind 127.0.0.1 -d dist
