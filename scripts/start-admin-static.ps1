$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "apps/admin-web")
npm.cmd run build
python -m http.server 5173 --bind 127.0.0.1 -d dist
