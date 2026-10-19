# AgentGuard

面向异构 LLM Agent 的工具调用安全中间件。**当前仅完成 P0 工程骨架；没有实际安全防护、
Agent、API 或 Benchmark 接入。** 后续开发必须逐阶段获得授权，实施依据为根目录
`AgentGuard_Codex_分阶段实施与验收计划.md` 和 `AGENTS.md`。

## 环境与安装

Python 3.11+；Node.js 22.12+（Vite 7 要求），npm 11。P0 实测版本见验收报告。
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

## 检查与结果

```powershell
.\.venv\Scripts\python.exe scripts/check_phase.py P0
# 单独排查：
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -m p0 --basetemp=.cache/pytest
npm.cmd --prefix apps/web run test
npm.cmd --prefix apps/web run build
```

`scripts/check_phase.py P0` 是跨平台的本地 `make check` 等价命令：执行依赖完整性、Ruff、
pytest、前端测试与生产构建。脚本仅接受 P0，其他阶段参数返回非零，不会提前执行。
任一步失败、JUnit 丢失或报告损坏均返回非零；跳过测试不会得到 PASS。
每次运行先移除本次使用的旧报告，避免把旧通过结果当作新结果。

机器结果写入 `reports/generated/P0-results.json`，包含真实命令、退出码、耗时、JUnit
测试统计和日志路径；Python/Web JUnit 与步骤日志保存在同目录。项目结论见
`reports/P0-acceptance.md`。generated 文件保留在本地但默认不提交。
pytest 自动移除凭据环境变量并阻止常见 socket 连接/DNS；临时文件在仓库 `.cache` 下。
这些测试隔离措施不构成操作系统级恶意代码沙箱。

## 目录与边界

| 路径 | P0 状态/用途 |
| --- | --- |
| `src/agentguard` | 可独立安装的空 SDK，只有版本和预留模块 |
| `apps/api` | 文档占位；FastAPI/LangGraph/DeepSeek 属于 P1 |
| `apps/web` | Vue 3 + Vite + Element Plus 空应用与挂载测试 |
| `tests/unit`, `tests/integration`, `tests/security` | P0 包、依赖隔离、验收器和离线环境检查 |
| `tests/e2e` | 文档占位；业务 E2E 属于 P7 |
| `configs`, `fixtures`, `benchmarks` | 后续配置、隔离样例、评测的占位说明 |
| `docs` | 架构、契约草案、威胁模型、评测接入计划 |
| `scripts`, `reports` | 阶段检查入口、真实执行结果与验收报告 |

默认 SDK 仅依赖 Pydantic v2。LangGraph/LangChain 仅允许进入后续可选 Adapter；
FastAPI、Vue、演示 Agent 与 Benchmark 不得成为 SDK 依赖。SQLite 会话和脱敏审计尚未实现。

## 安全与外部实验

`.env.example` 仅记录后续配置意图，P0 没有读取 `.env` 的代码或模型 Provider。
不要创建真实密钥用于 P0，不要把任何秘密置于 `VITE_` 变量（会进入浏览器构建）。
真实 API、Benchmark、无 Guard 基线在对应阶段均须显式开启，预算和凭据保护通过后才运行。
当前没有任何真实 DeepSeek 或四项 Benchmark 实验结果，也没有 Guard 阻断效果的声明。

技术细节见 [架构](docs/architecture.md)、[契约草案](docs/contracts.md)、
[威胁模型](docs/threat-model.md)、[评测计划](docs/evaluation-plan.md)。

