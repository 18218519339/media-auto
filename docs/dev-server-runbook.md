# Windows/Codex Dev Server Runbook

## Problem

Long-running commands such as `uvicorn`, `vite`, `npm run dev`, and fake workers do not return while the server is healthy. Running them directly through the Codex shell tool looks like a hang because the tool is waiting for the foreground process to exit.

The same applies to wrappers that keep a shell open, especially:

```powershell
cmd /c start "Title" cmd /k "..."
```

`cmd /k` is interactive by design, so do not use it from Codex tool calls.

## Fastest Fix

Use this sequence next time:

1. Run tests and builds in Codex shell because they exit.
2. Start long-lived servers in a separate terminal window, not in the active tool process.
3. Verify with HTTP health checks or `netstat`.
4. If a foreground server was accidentally started, interrupt it and do not wait.

## Safe Commands For This Project

Backend API in a new window:

```powershell
cmd /c start "Media Automation API" /D "C:\Users\Admin\Desktop\AD CODEX\apps\api-server" python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend admin in a new window:

```powershell
cmd /c start "Media Automation Admin" /D "C:\Users\Admin\Desktop\AD CODEX\apps\admin-web" npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

If Vite reports `failed to load config` with `Error: spawn EPERM`, make sure the project uses `vite.config.js` and the npm script passes `--config vite.config.js`. In this Windows/Codex environment, a TypeScript Vite config may require an esbuild child process during dev-server startup and fail in a detached window.

If Vite still reports `spawn EPERM`, skip the dev server entirely. Build once and serve static files with Python:

```powershell
cd "C:\Users\Admin\Desktop\AD CODEX\apps\admin-web"
npm.cmd run build
python -m http.server 5173 --bind 127.0.0.1 -d dist
```

For a human-owned Windows terminal, use the checked-in script:

```powershell
.\scripts\start-admin-static.cmd
```

The frontend defaults to `http://127.0.0.1:8000` for API calls, so it does not need the Vite proxy in static mode.

## Codex-Specific Rule

Do not launch any long-lived server from a Codex shell tool, even through nested `cmd /c start` wrappers. In this desktop environment, nested `cmd` wrappers can still keep the tool call attached and look stuck.

Fastest path:

1. Use Codex only for exiting checks: `pytest`, `npm run build`, file edits, and health checks.
2. Write or update `.cmd`/`.ps1` launch scripts.
3. Ask the human to run the launch script in their own terminal/window.
4. After they run it, Codex can verify with `Invoke-RestMethod`, `Invoke-WebRequest`, or `netstat`.

Commands now known to be bad inside Codex shell calls:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
npm.cmd run dev
python -m http.server 5173 --bind 127.0.0.1 -d dist
cmd /c start "Title" cmd /k "..."
cmd /c start "Title" /min cmd /c "..."
```

Health checks:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health"
Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing
netstat -ano | Select-String ":8000|:5173"
```

## Commands To Avoid In Codex Tool Calls

Avoid these unless the user explicitly wants a foreground server:

```powershell
python -m uvicorn app.main:app --reload
npm.cmd run dev
cmd /c start "Title" cmd /k "..."
```

They are fine in a human-owned terminal window, but they are the wrong shape for Codex automation.

## Current Lesson

If a command prints no prompt and appears stuck after launching a server, first assume it is a healthy foreground server. Do not keep waiting. Interrupt, then restart using the new-window command and verify with `/api/health`.

## Content Grounding Quality Gate

Before handing the media automation flow back to a human tester, run the exiting checks below:

```powershell
python -m pytest apps/api-server/tests -q
cd apps/admin-web
npm.cmd run build
```

The backend suite includes local HTML fixtures with unique material keywords such as `HBM3E`, `CoWoS`, and `DRAM现货价格`. A generated draft must carry those source-specific points forward. If a link cannot be read, the source body is too short, or an OpenClaw rewrite result is empty/unrelated, the system must fail with a clear log instead of producing a placeholder draft.
