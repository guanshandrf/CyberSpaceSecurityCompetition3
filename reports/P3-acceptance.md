# P3 验收报告

结论：**PASS（P3 范围）**。日期：2026-10-20（Asia/Shanghai）。最终机器结果时间：
2026-10-20T11:26:02.052070+00:00，即北京时间 19:26。

正式验收共 **336 passed、0 failed、0 errors、0 skipped**：334 项 Python（P0–P3）和
2 项既有前端测试。依赖检查、Ruff lint/format、前端生产构建均退出 0。
无 Agent/Web 框架的纯 SDK 环境另有 277 passed、57 deselected；这是正式结果的子集，
不重复计入 336。机器证据：reports/generated/P3-results.json、P3-python-junit.xml、
P3-web-junit.xml、P3-sdk-only-junit.xml 及六步日志；generated 默认忽略，不自动提交。

## 起始状态与实施范围

工作目录始终为 D:\Projects\Work\competition3，没有向父目录搜索/读取项目文件。
读取 AGENTS.md、阶段计划、architecture/contracts/threat-model 后开始。
起始 main 相对 origin/main ahead 2，为两个本地 P1 提交；P2 修改未提交。本轮保留这些内容，
在 P2 契约上实现 P3，没有重置/覆盖用户已有工作，也未自动 Git 提交或推送。
普通沙箱存在 setup refresh 进程启动错误，相关仓库命令通过工具授权执行。

实施顺序：复核契约和 P3 标准 → 公布实施方案 → 最小 Gate/策略/执行器/审计 → 行为与安全
测试 → 修复实际失败 → 累计验收和纯 SDK 验证 → 本报告 → 停止。

完成项：

| 产物 | 实际行为 |
| --- | --- |
| Gate1.before_tool / evaluate | 重验可信上下文与关联，检查工具摘要、任务、权限、资源、参数、路径和上下文预算，输出统一 SecurityDecision |
| ToolBinding / PathRule | 后端不可变配置；绑定 ID/名称/Schema/权限/任务/资源/路径/审批，按配置生成摘要；不是 P5 注册准入 |
| PolicyEngine | 可配置 blocked_tools / review_tools，拒绝优先；默认拒绝 detector findings；硬性权限检查不受 ALLOW/低风险结论覆盖 |
| GuardedExecutor | 不接收外部 Decision，每次执行重新检查；锁内记录意图和核销预算/调用 ID；BLOCK/未批准 REVIEW 零原工具调用 |
| 审批 | 不可预测引用、完整调用/上下文指纹、期限、后端审批者权限和 session 校验；批准后重新检查；拒绝/过期/变参/复用不能执行 |
| 预算与重放 | 单实例会话预算、可信已用量高水位和最小上限；更换上下文不能重置；调用 ID 和事件 ID 双重防重放；并发核销 |
| 路径限制 | 相对路径和受信资源根绑定，拒绝遍历/Windows 别名/链接/非普通文件；执行前重检并传规范绝对路径给 handler |
| SQLiteAudit | 实际 SQLite 写入；标识 HMAC、原因码白名单，不存参数/路径/结果/异常/审批 token；执行前审计失败默认拒绝 |
| 可重现样例 | examples/guarded_read.py 实际读取公共 fixture，验证 ALLOW/BLOCK/REVIEW/审批；2 次实际执行，不调用模型 |
| 验收入口 | check_phase.py P3 累计 P0–P3；P4 参数仍拒绝；前端按 P3 输出 JUnit |

SDK 版本 0.3.0，schema_version 仍为 1.0；运行依赖未增加，仍仅 Pydantic 2.12.4。
SDK 不 import LangGraph、LangChain、FastAPI、演示 Agent 或 Benchmark。
Gate 0、Gate 2、注册描述检测、结果过滤、LangGraph Adapter 和 Web 审批/审计界面均未开发。
P1 演示仍是默认关闭的无 Guard 基线，不能将 P3 独立 SDK 测试写成端到端模型防护。

## 新增及变更文件

- src/agentguard/gates/gate1.py 与 gates/__init__.py：Gate 1 和可信/事件快照。
- src/agentguard/policies/binding.py、schema.py、engine.py 与 __init__.py：工具配置、
  路径、严格 Schema 子集与可替换策略。
- src/agentguard/executor/guarded.py 与 __init__.py：执行结果、审批、预算和强制执行。
- src/agentguard/audit/store.py 与 __init__.py：字段白名单 SQLite 审计。
- tests/p3/conftest.py、test_enforcement.py、test_approval_audit.py、test_schema.py：
  隔离 fixtures、执行计数、并发/审批/异常/路径/审计安全测试，共 117 项。
- examples/guarded_read.py、docs/gate1.md、本报告：可运行示例、API/限制和验收。
- pyproject.toml、src/agentguard/__init__.py：0.3.0、P3 标记；无新运行依赖。
- scripts/check_phase.py、apps/web/vite.config.js：累计 P3 检查及 JUnit 前缀。
- tests/unit/test_package.py：保留 P0 架构断言，检查本阶段合法导出并禁止未来 Gate/Adapter；
  test_phase_runner.py 将拒绝对象从已授权 P3 改为 P4。没有删除测试或降低安全要求。
- README.md、docs/architecture.md、contracts.md、threat-model.md：当前交付、公共接口与限制。

## 环境与准确执行命令

Windows AMD64、Python 3.13.9、Pydantic 2.12.4、pytest 8.4.2、Ruff 0.12.0。
沿用既有 Python/npm 锁与已安装依赖；本轮未下载新依赖，没有访问真实 API。
所有下面的顶层命令均在项目根目录执行；使用普通包安装，不依赖 PYTHONPATH。

开发安装与实际 P3 回归：

```powershell
.\.venv\Scripts\python.exe -m ruff check . --fix
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest tests/p3 --basetemp=.cache/pytest-P3-dev --junitxml=reports/generated/P3-dev-junit.xml
```

最终代码重新安装并运行，P3 为 117 passed、0 failed/errors/skipped。阶段正式验收：

```powershell
.\.venv\Scripts\python.exe scripts/check_phase.py P3
```

该脚本实际执行的六步如下；完整 argv/cwd/退出码/耗时保存在机器 JSON：

```powershell
# cwd: D:\Projects\Work\competition3
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m pip check
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m ruff check .
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m ruff format --check .
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m pytest -m 'p0 or p1 or p2 or p3' --basetemp=.cache/pytest-P3 --junitxml=D:\Projects\Work\competition3\reports\generated\P3-python-junit.xml
# cwd: D:\Projects\Work\competition3\apps\web
& 'C:\Program Files\nodejs\npm.cmd' run test
& 'C:\Program Files\nodejs\npm.cmd' run build
```

纯 SDK 环境沿用仓库内已有的 p2-sdk-venv（未安装 Agent/Web 框架），本轮更新 SDK 后执行：

```powershell
.\.cache\p2-sdk-venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.cache\p2-sdk-venv\Scripts\python.exe -I -c "import importlib.util; import agentguard; assert agentguard.__version__=='0.3.0'; assert all(importlib.util.find_spec(n) is None for n in ['fastapi','langgraph','langchain_core','agentguard_demo']); print('P3 SDK-only framework independence: PASS')"
.\.cache\p2-sdk-venv\Scripts\python.exe -m pip check
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONUTF8='1'
.\.cache\p2-sdk-venv\Scripts\python.exe -m pytest -m 'p0 or p2 or p3' --basetemp=.cache/pytest-P3-sdk --junitxml=reports/generated/P3-sdk-only-junit.xml
```

结果：框架缺席断言 PASS、pip check PASS、277 passed、57 P1 deselected、0 skipped。
离线环境移除凭据、禁用真实 API/Benchmark/基线开关和 tracing，拒绝常见 socket/DNS；
Windows 标准库 socketpair 的本地 IPC 沿用 P1 的精确例外，普通回环和外网仍拒绝。
独立示例由自动化测试在 -I 子进程实际运行并核对结构化结果，不是伪造工具执行输出。

## 最终真实测试统计

| 范围 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| P0 Python 回归 | 34 | 0 | 0 | 0 |
| P1 Python 回归 | 57 | 0 | 0 | 0 |
| P2 Python 回归 | 126 | 0 | 0 | 0 |
| P3 授权、路径、异常、预算、并发、重放 | 70 | 0 | 0 | 0 |
| P3 审批、审计及独立示例 | 23 | 0 | 0 | 0 |
| P3 Schema 与配置 | 24 | 0 | 0 | 0 |
| 既有前端回归 | 2 | 0 | 0 | 0 |
| **合计** | **336** | **0** | **0** | **0** |

Ruff 格式检查覆盖 49 个 Python 文件。lint/build/pip check 不额外计入测试用例数。

## 逐项验收与人工核对

1. 授权文件读取 ALLOW：真实公共 fixture 内容与预期一致，原工具计数为 1。
2. 未授权路径 BLOCK：遍历、绝对/盘符/UNC、ADS、设备名、尾点空格、缺失文件等均拒绝，
   原工具计数为 0。实际硬链接与 Windows 目录联接（子目录及替换资源根）同样拒绝。
3. 非法参数 BLOCK：缺参、类型、额外字段、bool/number、数组/对象与边界限制覆盖；
   不支持 Schema 关键字在配置时拒绝，不执行引用、不读取外部 Schema。
4. 重复/超预算 BLOCK：两个 ID 任一复用即拒绝；线程池 8 worker/16 请求分别验证同调用
   重试和不同调用竞争仅一次执行。后端预算耗尽一旦被观察，旧上下文不能恢复预算。
5. 策略/检测异常、非法输出、缺失/伪造上下文、低风险 ALLOW 不能覆盖硬权限拒绝；
   审计前置故障也零执行。工具异常只暴露通用代码，已执行调用不允许旧 ID 重试。
6. REVIEW 未批准零副作用，approve 本身不执行；错误身份/权限/session/token 拒绝，
   批准后变更参数/event/trace/context/摘要、过期/拒绝、当前策略或路径改变均不能绕过。
7. 并发审批后重试只执行一次；execute 不接受外部旧 Decision；传入嵌套参数变更会重验，
   插件收到分离快照，不能通过修改其参数副本改变实际执行参数。
8. 审计真实落 SQLite，自动化断言参数、路径、原始输出、异常、原始标识和审批 token
   均未记录。审计标识 HMAC 保留同实例关联；自定义原因码归一为 policy.custom。

人工复核：SDK 默认依赖与框架隔离保持；P1 Agent 未接入；所有路径/链接测试端点均在
仓库隔离 fixtures 内。没有浏览器业务验收，本阶段未新增 UI。

## 发现的问题与修复记录

- 首轮 110 项测试真实结果为 104 passed、6 failed、0 skipped。五个失败涉及 Python 3.13
  检出的 SQLite 连接未关闭告警；另一个发现 ExecutionResult.repr 带出了自定义决策中的
  合成敏感标识。修复为显式 closing+事务，以及隐藏整个 decision 的 repr，原失败测试
  全部保留；随后 110 项全通过。没有真实凭据用于测试输入。
- 首次 lint 有导入顺序/长行问题，格式化、拆分后全部通过，没有禁用规则。
- 补充真实目录联接、非法 detector 输出、async handler 配置拒绝、独立实际 I/O 示例后，
  116 项 P3、333 项累计 Python 和 2 项前端通过。
- 最终复核收紧预算：可信上下文报告耗尽时，即使本次调用被拒绝也应更新账本高水位。
  将可信关联校验和账本观察前置，增加旧上下文无法恢复预算的回归。最终重新安装与
  完整验收为 117 项 P3、334 项累计 Python、2 项前端通过。

## 未验证能力与已知限制

- **真实 DeepSeek：本轮 NOT_RUN；四项 Benchmark：NOT_RUN**。历史 P1 的真实只读冒烟
  记录在 reports/P1-deepseek-real.md，不能冒充 P3 防护/Benchmark 成绩。本轮未消费 API 额度。
- 仅 SDK 执行器接管的同步调用受保护。P1 仍未接入；原始 handler 引用、框架内置/托管
  工具旁路、第三方任意代码不在保护承诺内。ToolBinding 不是 Gate 0/工具可信证明。
- Schema 仅严格支持 docs/gate1.md 的子集，不支持完整 JSON Schema；未知关键字拒绝配置。
- 预算/审批/重放只有单执行器单进程锁保护，重启/多 worker 不共享；无事务恢复或分布式
  exactly-once 保证。账本/过期审批未做持久化或长期服务回收，需后续工程加固。
- 路径为资源根级授权、静态检查与执行前重检；不能阻止本机恶意进程在检查和 open 间
  改文件，或受信工具忽略路径参数。工具仍须自身沙箱、独占写/安全句柄与主机保护。
- SecurityContext.from_backend 和 approve 是可信应用入口，不能代替认证、签名或隔离。
  后端须选择当前上下文、生成/管理 session 并鉴权审批者，禁止直接采信模型/客户端声明。
- Gate 2 未实现，ExecutionResult.value 为原始工具内容，尚未检测注入/脱敏；本阶段不声称
  结果可安全进入模型，也不能撤销工具副作用。
- SQLiteAudit 为最小字段白名单存储，HMAC salt 每实例随机、重启不保持关联；无 UI、访问
  控制、审计保留/轮换或防篡改。执行后审计故障会明确 executed=True，不能撤销副作用。
- 仅 Windows/Python 3.13.9 实测；其他平台/Python 版本未实测。首次依赖安装需预备缓存，
  Python 锁仍是版本锁而非哈希锁。

P3 验收范围内无阻塞遗留问题。下一阶段建议按原计划实施 P4 结果检查，须用户另行明确授权。
**本轮停止于 P3，不进入 P4；代码与报告留待用户检查，未自动提交或推送。**
