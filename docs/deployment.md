# 安装、演示与交付边界

所有命令从仓库根目录运行。Python 3.11+，实测 Windows Python 3.13.9；Web 使用 Node22+
和 npm。SDK 运行依赖仅 Pydantic。Demo 和 Benchmark 是独立安装包，见根 README 与
benchmarks/README.md。首次准备依赖需网络；有匹配平台缓存后可离线重建。

```powershell
New-Item -ItemType Directory -Force .cache/task-temp | Out-Null
$env:TEMP=(Join-Path (Get-Location) '.cache/task-temp')
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-dev.lock -r requirements-demo.lock
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps . apps/api .\benchmarks
.\.venv\Scripts\python.exe scripts/check_phase.py P9
.\.venv\Scripts\python.exe examples/simple_agent.py
.\.venv\Scripts\python.exe scripts/stress_simple.py --calls 200
```

前端先按 README 的 npm ci 命令安装。正式入口 P9 包含 P0–P9 Python、依赖边界、Ruff
静态/格式、全部 Web 测试与生产构建，输出 reports/generated/P9-results.json 与 JUnit。
验收脚本通过不能替代独立启用的真实 API 或完整官方 Benchmark 验收。

本地演示启动：

```powershell
$env:AGENTGUARD_LLM_PROVIDER='fake'
$env:AGENTGUARD_ENABLE_PROTECTION='true'
$env:AGENTGUARD_ENABLE_BASELINE='false'
.\.venv\Scripts\python.exe -m uvicorn agentguard_demo.api:app --host 127.0.0.1 --port 8000
# 在另一个同样以根目录为工作目录的终端：
npm.cmd --prefix apps/web run dev
```

浏览器访问 http://127.0.0.1:5173。试用受控命令见 docs/web-chat.md。API 默认关闭 Agent，
开启保护不需要真实 Key；界面“显示安全审计”只控制展示。没有登录体系，不能直接绑定公网。
Vite 构建由现有本地 preview/proxy 演示，不把 dist 静态目录本身当完整后端部署。

真实 Key 只能由忽略的根 .env 或进程环境配置，不进入日志/Git/浏览器。真实 API 与下载/
评测均须显式开启。此次授权总量20次，每次256输出token，实际已用18次；保留
.cache/p8-live/budget.sqlite，不得删除账本或换目录扩大本次预算。

SDK 审计和 Web 展示历史是不同 SQLite 数据库，需按本地敏感数据保护。运行中会话的预算/
审批/防重放为单进程内存；重启后历史只读，不恢复可执行会话。不要多 worker 共享同一
会话期待全局预算。没有生产认证、分布式协调、审计归档治理或工具进程隔离。

压力探针使用真实本地 SQLite 和无害 echo，含序列化/三Gate/审计开销，不能外推生产 SLA。
规则检测有漏报/误报，P8 展示了阻断污染结果造成可用性损失；不会承诺消除提示注入。
完整原生 MSB MCP 和 τ³ 全任务评测仍未验证。最终范围与结果以 reports/final-acceptance.md
和各阶段报告为准，P8 PARTIAL 不能被工程测试 PASS 覆盖。
