# AgentGuard

面向异构 LLM Agent 的工具调用安全中间件。**当前实现至 P7：三 Gate、注册表、受控执行、
LangGraph 接入及聊天/逐调用安全审计界面；独立基线保留，Benchmark 尚未接入。**
后续开发必须逐阶段获得授权，实施依据为根目录
`AgentGuard_Codex_分阶段实施与验收计划.md` 和 `AGENTS.md`。

## 环境与安装

Python 3.11+；Node.js 22.12+（Vite 7 要求），npm 11。实测版本见各阶段验收报告。
以下 PowerShell 命令均在项目根目录执行，不需要管理员权限、`.env` 或 DeepSeek Key。
首次取得依赖需要网络；测试和构建使用本地依赖，均不需要联网。
先确认所用解释器为 Python 3.11+；多 Python 环境不要用指向 3.10 的别名创建虚拟环境。

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
**可选手动步骤**见 [演示包说明](apps/api/README.md)。2026-10-20 已显式运行一次受控真实
工具冒烟，见 [补充报告](reports/P1-deepseek-real.md)；常规检查不调用真实 API。
执行会话仍在单进程内存中；P7 保护模式另有 SQLite 安全历史，重启后的旧会话只读。
逐 token 输出尚未实现，现为逐节点 SSE。

## P7 聊天界面与逐条审计

保护模式启动 API 后，在另一个根目录终端执行 `npm.cmd --prefix apps/web run dev`，
访问 http://127.0.0.1:5173。会话列表、流式状态、工具审核卡片和历史查询已接入；
“显示安全审计”仅控制展示。配置、接口及本地安全边界见 [P7 使用说明](docs/web-chat.md)。
默认配置仍不开启任何 Agent，需显式设置 AGENTGUARD_ENABLE_PROTECTION=true、
AGENTGUARD_ENABLE_BASELINE=false。P7 入口为 `python scripts/check_phase.py P7`，
验收结果见 [P7 报告](reports/P7-acceptance.md)。不默认调用真实 API 或 Benchmark。

## P2 SDK 契约

`agentguard.contracts` 提供 SecurityEvent、ToolRegistrationEvent、ToolCallEvent、
ToolResultEvent、SecurityContext、SecurityFinding、SecurityDecision、CallBudget、
Detector/Policy/Gate Protocol、parse_event 和 validate_correlation。
固定 schema 1.0，严格类型/额外字段拒绝，JSON/大小/截断元数据限制和 ID 关联检查。
SecurityContext 只能由可信后端显式构造，不能反序列化模型自报权限；它不代替身份认证。
契约本身不授权执行；P3 的 GuardedExecutor 提供独立调用前保护，见下一节。

```powershell
.\.venv\Scripts\python.exe examples/mock_adapter.py
.\.venv\Scripts\python.exe scripts/check_phase.py P2
# 只安装 SDK/开发依赖的环境也能执行，P1 测试会被 deselect：
.\.venv\Scripts\python.exe -m pytest -m 'p0 or p2' --basetemp=.cache/pytest-P2-sdk
```

公共 API、输入边界与后端构造示例见 [契约文档](docs/contracts.md)。Mock Adapter
只生成合成事件，不调用任何工具、真实模型或 Benchmark。

## P3 受控工具执行

`agentguard.policies` 提供 ToolBinding/PathRule/PolicyEngine；`agentguard.gates.Gate1`
提供 before_tool；`agentguard.executor.GuardedExecutor` 重新校验并执行，BLOCK 和未批准
REVIEW 不调用原工具；`agentguard.audit.SQLiteAudit` 保存字段白名单审计。
后端必须共享执行器并提供真实可信上下文/审批者，不能从模型 JSON 导入权限。
Schema 采用明确的严格子集，不支持的关键字直接拒绝配置；预算/重放仅保证单实例单进程。
文件路径静态检查不能隔离任意 Python handler 或抵抗恶意本机进程竞态。
单独使用执行器时，返回 value 仍未经结果检查；应使用 P4 ResultHandler，或 P6 Adapter 闭环。
完整 API、配置、审批流程和限制见 [P3 文档](docs/gate1.md)。
P3 审计加固增加审批容量/限流/回收、锁外检测和后端撤权重验，并补全 Windows 设备名。
本轮修复验证见 [P3 安全修复验收](reports/P3-security-fix-acceptance.md)。

```powershell
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.venv\Scripts\python.exe examples/guarded_read.py
.\.venv\Scripts\python.exe scripts/check_phase.py P3
```

示例只创建仓库内临时公共文件，用真实本地读取演示 ALLOW/BLOCK/REVIEW/审批，不调用模型。

## P4–P6：三 Gate 与 LangGraph 闭环

Gate2/ResultHandler 分离原始与安全结果，Gate0/ToolRegistry 处理注册、更新、TTL 和撤销。
P6 的 `agentguard.adapters.langgraph.protect` 构建受保护工具包装和 StateGraph 节点；
同一会话复用执行器，模型仅收到安全 ToolMessage。SDK 默认仍只依赖 Pydantic；可选
`langgraph` extra 使用与演示锁文件相同的框架版本。详细配置与覆盖边界见
[接入说明](docs/langgraph.md)、[Gate0](docs/gate0.md)、[Gate2](docs/gate2.md)。

先完成 SDK 与演示包安装，再运行离线保护模式：

```powershell
$env:AGENTGUARD_ENABLE_BASELINE='false'
$env:AGENTGUARD_ENABLE_PROTECTION='true'
$env:AGENTGUARD_LLM_PROVIDER='fake'
$env:AGENTGUARD_ENABLE_REAL_API='false'
.\.venv\Scripts\python.exe -m uvicorn agentguard_demo.api:app --host 127.0.0.1 --port 8000
```

两种模式互斥且默认均关闭；客户端不能切换 Guard。保护模式仅覆盖 Adapter 接管的工具，
不覆盖另建原始 ToolNode、框架内置/托管工具或恶意 Python 代码。审计保存在沙箱
audit.sqlite，仅供后端检查；P7 Web 审计界面尚未开发。

## 检查与结果

```powershell
.\.venv\Scripts\python.exe scripts/check_phase.py P0
.\.venv\Scripts\python.exe scripts/check_phase.py P1
.\.venv\Scripts\python.exe scripts/check_phase.py P2
.\.venv\Scripts\python.exe scripts/check_phase.py P3
.\.venv\Scripts\python.exe scripts/check_phase.py P4
.\.venv\Scripts\python.exe scripts/check_phase.py P5
.\.venv\Scripts\python.exe scripts/check_phase.py P6
# 单独排查：
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -m 'p0 or p1 or p2 or p3 or p4 or p5 or p6' --basetemp=.cache/pytest-current
npm.cmd --prefix apps/web run test
npm.cmd --prefix apps/web run build
```

`scripts/check_phase.py P0` 是跨平台的本地 `make check` 等价命令：执行依赖完整性、Ruff、
pytest、前端测试与生产构建。每阶段运行累计回归，P6 包含 P0–P6；
脚本仅接受已实现的 P0–P6，P7 及以后参数返回非零。
任一步失败、JUnit 丢失或报告损坏均返回非零；跳过测试不会得到 PASS。
每次运行先移除本次使用的旧报告，避免把旧通过结果当作新结果。

机器结果写入 `reports/generated/Pn-results.json`（n 为 0–6），包含真实命令、退出码、耗时、JUnit
测试统计和日志路径；Python/Web JUnit 与步骤日志保存在同目录。项目结论见
`reports/P0-acceptance.md`、`reports/P1-acceptance.md`、`reports/P2-acceptance.md`（历史）与 `reports/P3-acceptance.md`。
generated 文件保留在本地但默认不提交。
pytest 自动移除凭据环境变量并阻止常见 socket 连接/DNS；临时文件在仓库 `.cache` 下。
Windows asyncio 所需的标准库 socketpair 本地 IPC 被单独允许，普通回环/外网连接仍被拒绝。
这些测试隔离措施不构成操作系统级恶意代码沙箱。

## 目录与边界

| 路径 | 当前状态/用途 |
| --- | --- |
| `src/agentguard` | 可独立安装的 0.6.0 SDK，三 Gate/注册表/Executor 和可选 Adapter |
| `apps/api` | 独立基线及 P6 保护模式，LangGraph/FastAPI/Fake/可选 DeepSeek Provider |
| `apps/web` | Vue 3 + Vite + Element Plus 空应用与挂载测试 |
| `tests/unit`, `tests/integration`, `tests/security` | P0 包、依赖隔离、验收器和离线环境检查 |
| `tests/p1` | P1 API/SSE、Provider、沙箱与依赖测试 |
| `tests/p2`, `examples` | P2 数据契约、伪造/关联测试和不执行工具的 Mock Adapter |
| `tests/p3` | Gate 1、实际执行计数、审批/预算/重放、路径和审计回归 |
| `tests/p4`–`tests/p6` | 结果/注册安全与真实 LangGraph + Fake 的端到端回归 |
| `tests/e2e` | 文档占位；业务 E2E 属于 P7 |
| `configs`, `fixtures`, `benchmarks` | 后续配置、隔离样例、评测的占位说明 |
| `docs` | 架构、契约草案、威胁模型、评测接入计划 |
| `scripts`, `reports` | 阶段检查入口、真实执行结果与验收报告 |

默认 SDK 仅依赖 Pydantic v2。SDK 内 LangGraph/LangChain 只允许进入可选 Adapter；
FastAPI、Vue、演示 Agent 与 Benchmark 不得成为 SDK 依赖。SQLite 最小审计已实现，会话持久化尚未实现。

## 安全与外部实验

`.env.example` 中所有外部/无 Guard 开关默认关闭，Fake 默认启用。通过 uvicorn
`--env-file .env` 显式读取环境文件；API 请求不能覆盖服务端 Provider 或权限配置。
不要把任何秘密置于 `VITE_` 变量（会进入浏览器构建）。真实 API 还需独立开关、服务端密钥，
受每会话和每进程调用数、每响应 token 上限限制，无自动重试；重启进程会重置本地计数。
这些限制用于本地实验，不是 SDK Guard 或账户级费用保证。Benchmark 仍未实现。
已记录一次 P1 真实 DeepSeek 正常工具冒烟；P3 验证本地受控调用阻断，不代表真实模型或 Benchmark 实验。

技术细节见 [架构](docs/architecture.md)、[契约草案](docs/contracts.md)、
[威胁模型](docs/threat-model.md)、[评测计划](docs/evaluation-plan.md)。

