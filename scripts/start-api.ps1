$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "apps/api-server")
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
