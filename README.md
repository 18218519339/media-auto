# 媒体自动分发 MVP

这是一个本机/内网优先运行的媒体自动分发 MVP，包含：

- FastAPI 后端：素材、草稿、公众号配置、排期、流水线日志、OpenClaw worker 协议。
- React/Vite 管理台：仿写工作台、草稿审核、发布计划、流水线日志、公众号配置。
- fake OpenClaw worker：用于在没有真实平台账号时模拟改写和发布回传。

## 本地启动

Codex 自动化环境里不要直接前台运行长驻服务。遇到“卡住”时看 [Windows/Codex Dev Server Runbook](docs/dev-server-runbook.md)。

后端：

```powershell
.\scripts\start-api.ps1
```

或双击/运行：

```powershell
.\scripts\start-api.cmd
```

前端：

```powershell
.\scripts\start-admin.ps1
```

打开 `http://127.0.0.1:5173` 使用管理台。API 默认运行在 `http://127.0.0.1:8000`。

如果 Vite dev server 在 Windows/Codex 环境中遇到 `spawn EPERM`，使用生产构建静态服务：

```powershell
.\scripts\start-admin-static.ps1
```

或双击/运行：

```powershell
.\scripts\start-admin-static.cmd
```

## 验证命令

```powershell
python -m pytest apps/api-server/tests/test_mvp_workflow.py -q
cd apps/admin-web
npm.cmd run build
```

## OpenClaw 协议

真实 OpenClaw worker 可以使用这些接口：

- `GET /api/openclaw/tasks/next`
- `POST /api/openclaw/tasks/{id}/events`
- `POST /api/openclaw/tasks/{id}/result`

本地模拟 worker：

```powershell
python apps/api-server/scripts/fake_openclaw_worker.py
```

调度器可以通过管理台“运行调度器”按钮触发，也可以直接调用：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/scheduler/run-due
```

## 安全说明

- 公众号 `AppSecret` 使用 `MEDIA_AUTOMATION_SECRET_KEY` 派生密钥后加密落库。
- 本地未设置 `MEDIA_AUTOMATION_SECRET_KEY` 时会使用开发默认密钥，只适合本机试跑。
- 小红书登录态和平台发布动作不保存在管理系统内，交给 OpenClaw 执行环境处理。
