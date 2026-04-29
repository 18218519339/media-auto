# WeChat OpenClaw Worker Startup Script
# Usage: .\scripts\start-wechat-worker.ps1

$ErrorActionPreference = "Stop"
$BASE_DIR = Split-Path -Parent $PSScriptRoot
$API_SERVER_DIR = Join-Path $BASE_DIR "apps\api-server"

$env:PYTHONPATH = "$API_SERVER_DIR;$env:PYTHONPATH"
$env:OPENCLAW_API_BASE = "http://127.0.0.1:8000"
$env:OPENCLAW_POLL_INTERVAL = "10"

Write-Host "Starting WeChat OpenClaw Worker..." -ForegroundColor Cyan
Write-Host "API Base: $env:OPENCLAW_API_BASE" -ForegroundColor Gray
Write-Host "Poll Interval: $env:OPENCLAW_POLL_INTERVAL seconds" -ForegroundColor Gray
Write-Host ""

try {
    python (Join-Path $API_SERVER_DIR "scripts\wechat_openclaw_worker.py")
} catch {
    Write-Host "Error starting worker: $_" -ForegroundColor Red
    exit 1
}