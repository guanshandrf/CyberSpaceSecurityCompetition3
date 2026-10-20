# AgentGuard

面向异构 LLM Agent 的工具调用安全中间件。**当前为 P1 无 Guard 的本地 LangGraph 基线，
默认 Fake LLM；SDK 仍是空骨架，没有实际安全防护或 Benchmark 接入。** 后续开发必须逐阶段获得授权，实施依据为根目录
`AgentGuard_Codex_分阶段实施与验收计划.md` 和 `AGENTS.md`。

## 环境与安装

Python 3.11+；Node.js 22.12+（Vite 7 要求），npm 11。实测版本见各阶段验收报告。
以下 PowerShell 命令均在项目根目录执行，不需要管理员权限、`.env` 或 DeepSeek Key。
首次取得依赖需要网络；测试和构建使用本地依赖，均不需要联网。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip --isolated download --index-url https://pypi.org/simple --disable-pip-version-check --no-cache-dir --only-binary=:all: --dest .cache/wheels -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
npm.cmd --prefix apps/web ci --cache .cache/npm --no-audit --no-fund
.\.venv\Scripts\python.exe scripts/check_phase.py P0
```

Linux/macOS 将 `.\.venv\Scripts\python.exe` 替换为 `.venv/bin/python`，`npm.cmd` 替换为
`npm`。跨系统/其他 Python 版本尚未实测；锁文件包含 Windows 的条件依赖 colorama。
Python 锁定直接、传递及构建依赖的精确版本，不包含哈希；npm 锁文件包含 integrity。
变更 Python 源码后重新执行包安装命令；测试有意验证已安装包，未设置源目录 PYTHONPATH。
本地迭代可改用 `install --no-index --no-build-isolation --no-deps -e .`，正式验收使用普通安装。

离线重建要求先在相同平台/Python 版本上准备 `.cache/wheels` 和 npm 缓存，再执行上述
两个 `pip install`，以及 `npm.cmd --prefix apps/web ci --offline --cache .cache/npm --no-audit --no-fund`。
缓存不纳入版本控制；空机器没有缓存时不能宣称支持无网络首次安装。

## P1 基线安装与启动

先完成上述 SDK 安装。演示包有独立依赖，SDK 默认安装不会拉取 LangGraph 或 FastAPI：

```powershell
.\.venv\Scripts\python.exe -m pip --isolated download --index-url https://pypi.org/simple --only-binary=:all: --dest .cache/wheels -r requirements-demo.lock
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-demo.lock
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps apps/api
.\.venv\Scripts\python.exe scripts/check_phase.py P1
# 显式启用无 Guard 的本地实验基线；仍使用 Fake，不需要 .env 或 API Key。
$env:AGENTGUARD_ENABLE_BASELINE='true'
.\.venv\Scripts\python.exe -m uvicorn agentguard_demo.api:app --host 127.0.0.1 --port 8000
```

安装源代码修改后需重新安装演示包；本地开发可用 `-e apps/api`。如果索引元数据请求缓慢，
下载命令可加 `--no-deps --use-deprecated=legacy-resolver`，此时必须使用完整锁文件；
安装仍使用正常解析器并执行 `pip check`。此参数依赖当前 pip 的兼容支持。

无 Guard 基线默认关闭，未显式开启时会话/聊天返回 503。仅绑定本地回环地址使用，
没有登录或多用户权限体系。API、工具参数、节点级 SSE、Fake 命令及真实 DeepSeek 的
**可选手动步骤**见 [演示包说明](apps/api/README.md)；本轮不运行真实 DeepSeek。
会话仅在进程内存中，重启丢失；SQLite 持久化和逐 token 输出尚未实现。

## 检查与结果

```powershell
.\.venv\Scripts\python.exe scripts/check_phase.py P0
.\.venv\Scripts\python.exe scripts/check_phase.py P1
# 单独排查：
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -m 'p0 or p1' --basetemp=.cache/pytest-current
npm.cmd --prefix apps/web run test
npm.cmd --prefix apps/web run build
```

`scripts/check_phase.py P0` 是跨平台的本地 `make check` 等价命令：执行依赖完整性、Ruff、
pytest、前端测试与生产构建。P1 会运行 P0 + P1 测试；脚本仅接受 P0/P1，P2 及以后参数返回非零。
任一步失败、JUnit 丢失或报告损坏均返回非零；跳过测试不会得到 PASS。
每次运行先移除本次使用的旧报告，避免把旧通过结果当作新结果。

机器结果写入 `reports/generated/P0-results.json` 或 `P1-results.json`，包含真实命令、退出码、耗时、JUnit
测试统计和日志路径；Python/Web JUnit 与步骤日志保存在同目录。项目结论见
`reports/P0-acceptance.md`（历史）和 `reports/P1-acceptance.md`。generated 文件保留在本地但默认不提交。
pytest 自动移除凭据环境变量并阻止常见 socket 连接/DNS；临时文件在仓库 `.cache` 下。
Windows asyncio 所需的标准库 socketpair 本地 IPC 被单独允许，普通回环/外网连接仍被拒绝。
这些测试隔离措施不构成操作系统级恶意代码沙箱。

## 目录与边界

| 路径 | 当前状态/用途 |
| --- | --- |
| `src/agentguard` | 可独立安装的空 SDK，只有版本和预留模块 |
| `apps/api` | 独立 P1 演示包，LangGraph/FastAPI/Fake/可选 DeepSeek Provider |
| `apps/web` | Vue 3 + Vite + Element Plus 空应用与挂载测试 |
| `tests/unit`, `tests/integration`, `tests/security` | P0 包、依赖隔离、验收器和离线环境检查 |
| `tests/p1` | P1 API/SSE、Provider、沙箱与依赖测试 |
| `tests/e2e` | 文档占位；业务 E2E 属于 P7 |
| `configs`, `fixtures`, `benchmarks` | 后续配置、隔离样例、评测的占位说明 |
| `docs` | 架构、契约草案、威胁模型、评测接入计划 |
| `scripts`, `reports` | 阶段检查入口、真实执行结果与验收报告 |

默认 SDK 仅依赖 Pydantic v2。SDK 内 LangGraph/LangChain 只允许进入后续可选 Adapter；
FastAPI、Vue、演示 Agent 与 Benchmark 不得成为 SDK 依赖。SQLite 会话和脱敏审计尚未实现。

## 安全与外部实验

`.env.example` 中所有外部/无 Guard 开关默认关闭，Fake 默认启用。通过 uvicorn
`--env-file .env` 显式读取环境文件；API 请求不能覆盖服务端 Provider 或权限配置。
不要把任何秘密置于 `VITE_` 变量（会进入浏览器构建）。真实 API 还需独立开关、服务端密钥，
受每会话和每进程调用数、每响应 token 上限限制，无自动重试；重启进程会重置本地计数。
这些限制用于本地实验，不是 SDK Guard 或账户级费用保证。Benchmark 仍未实现。
当前没有任何真实 DeepSeek 或四项 Benchmark 实验结果，也没有 Guard 阻断效果的声明。

技术细节见 [架构](docs/architecture.md)、[契约草案](docs/contracts.md)、
[威胁模型](docs/threat-model.md)、[评测计划](docs/evaluation-plan.md)。

