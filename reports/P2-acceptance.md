# P2 验收报告

- 阶段编号：P2 — 统一事件协议与安全决策接口。
- 日期：2026-10-20（Asia/Shanghai）；正式阶段检查完成于 11:58:51。
- 结论：**PASS，仅限 P2 契约与接口**。没有 Gate/Policy Engine/Executor 实现，不宣称运行时防护。
- 正式累计自动化测试：**通过 219 / 失败 0 / 错误 0 / 跳过 0**（Python 217 + Web 2）。
- 无 Agent 环境补充检查：**通过 160 / 失败 0 / 错误 0 / 跳过 0**，P1 用例 57 项 deselected。
- 机器结果：`reports/generated/P2-results.json`，时间戳
  `2026-10-20T03:58:51.521563+00:00`，包含真实子命令、cwd、退出码、耗时与测试统计。

## P1 提交和真实 API 前置事项

按本轮授权，先完成 P1，再验证真实 API，成功后才实施 P2：

| 事项 | 真实结果 |
| --- | --- |
| P1 实现提交 | `811d95985ef346075fff8eecd5dc8fc3b0a71eb5` |
| P1 真实验证/开关测试/补充报告提交 | `cbeafd9`，完整哈希可由本地 Git 获取 |
| Key | 已存在于进程环境；没有要求用户贴到聊天，没有创建 .env 或记录密钥 |
| DeepSeek | 2 次真实 HTTPS 200，模型调用 read_file 并返回与新建公开沙箱文件一致的内容 |
| API usage | prompt 849、completion 55、total 904；费用未计算 |
| 限制 | 最多 2 次请求、每次最多 128 输出 tokens、超时 15 秒、无重试、无笔记写入 |

细节见 `reports/P1-deepseek-real.md` 和脱敏机器证据
`reports/generated/P1-deepseek-real.json`。这是一次真实模型正常工具冒烟，未使用
Fake/MockTransport，但它不是 Benchmark 或 Guard 阻断效果测试。
P2 阶段检查仍全程离线：机器结果中的 `external_runs.deepseek=NOT_RUN` 表示该次离线
检查没有再调用 API，不否认前述独立真实验证。四项 Benchmark 始终未下载、未接入、未运行。

P1 两个提交仅在本地，未推送远端。P2 当前改动也尚未提交，保留供用户检查。

## P2 完成范围与产物

| 要求 | 交付 |
| --- | --- |
| 可独立安装的 SDK 契约层 | agentguard 0.2.0，默认依赖仍只有 Pydantic 2.12.4，不引入 Agent/Web/Benchmark |
| 三类统一事件 | SecurityEvent 公共 envelope；ToolRegistrationEvent、ToolCallEvent、ToolResultEvent；parse_event 判别解析 |
| 可信上下文 | SecurityContext.from_backend 显式后端入口，私有进程内来源标记；不可变身份/权限/资源/CallBudget，拒绝未受信反序列化 |
| 发现与统一决策 | SecurityFinding、Severity、SecurityDecision、DecisionAction；动作适用 Gate、必需 ID 和替换内容验证 |
| 关联校验 | validate_correlation 绑定上下文、session、调用/结果、工具元数据摘要引用、trace 和事件/决策 Gate；不决定授权 |
| 拓展接口 | 同步结构化 Detector / Policy / Gate Protocol，统一输入事件与上下文、输出发现/决策；无默认 ALLOW |
| 公共文档与样例 | docs/contracts.md 已从草案更新为实际 API；examples/mock_adapter.py 在无框架环境归一化三类合成事件，实际工具执行数为零 |
| 分阶段验收 | check_phase.py P2 运行 P0+P1+P2，前端按 P2 输出 JUnit；P3+ 参数仍拒绝 |

固定 schema_version=1.0，缺失版本或未知版本/字段/动作不被悄悄接受。JSON 深度/大小、
有限值/键类型、时间时区、ID 格式、结果错误标志与截断溯源均有行为测试。
SecurityContext 入口不等于身份认证；只有可信后端调用者可以赋予其业务含义。
没有实现执行授权、审批、预算核销、防重放、Gate 0/1/2 或真实 LangGraph 安全 Adapter。

## 新增/变更文件

新增：

- `src/agentguard/contracts/models.py`：事件、上下文、预算、发现、决策和解析。
- `src/agentguard/contracts/correlation.py`：纯关联验证与 CorrelationError。
- `src/agentguard/contracts/interfaces.py`：Detector/Policy/Gate Protocol。
- `examples/mock_adapter.py`：不执行工具、不调用模型的合成协议对照样例。
- `tests/p2/conftest.py`、`test_context.py`、`test_correlation.py`、`test_decisions.py`、
  `test_events.py`、`test_interfaces_and_example.py`：126 项新增 P2 用例。
- 本报告及本地忽略的 `reports/generated/P2-*` 日志/JSON/JUnit。

修改：

- `src/agentguard/__init__.py`、`contracts/__init__.py`、`pyproject.toml`：SDK 0.2.0、公共导出、p2 标记。
- `scripts/check_phase.py`、`apps/web/vite.config.js`：P2 累计验收与结果前缀。
- `README.md`、`apps/api/README.md`、`docs/architecture.md`、`docs/contracts.md`、
  `docs/threat-model.md`：当前实现、真实 P1 验证记录与信任边界。
- `tests/unit/test_package.py`：版本断言改为源码声明/安装元数据一致；contracts 模块由
  “预留空模块”改为公共契约导出检查，其他预留模块仍要求为空。
- `tests/integration/test_installation.py`、`tests/security/test_boundaries.py`：保留独立安装/
  框架隔离检查，增加 langchain_core 的禁止依赖检查，版本不再硬编码旧 0.0.0。
- `tests/unit/test_phase_runner.py`：越阶段拒绝对象由已授权 P2 更新为 P3。

这些回归断言随已授权产物演进，没有删除失败测试或放宽安全要求。
除 contracts 外，SDK core/gates/detectors/policies/executor/adapters/audit 仍是预留模块。

## 环境与准确执行命令

工作目录：`D:\Projects\Work\competition3`；Windows AMD64、Python 3.13.9、pip 25.2、
Pydantic 2.12.4、pytest 8.4.2、Ruff 0.12.0。演示和前端依赖沿用 P1/P0 精确锁文件。
本轮 P2 无需下载新依赖，均使用已准备的仓库内 wheel 缓存；新环境不继承系统 site-packages。
授权进程 PATH 中的 python 曾是 3.10，所以明确用仓库已有的 3.13 解释器创建环境。

无 Agent 环境的实际安装/验证命令：

```powershell
.\.venv\Scripts\python.exe -m venv .cache/p2-sdk-venv
.\.cache\p2-sdk-venv\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-dev.lock
.\.cache\p2-sdk-venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.cache\p2-sdk-venv\Scripts\python.exe -I -c "import importlib.util; import agentguard; assert agentguard.__version__=='0.2.0'; assert all(importlib.util.find_spec(n) is None for n in ['fastapi','langgraph','langchain_core','agentguard_demo']); print('P2 SDK-only framework independence: PASS')"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONUTF8='1'
.\.cache\p2-sdk-venv\Scripts\python.exe -m pytest -m 'p0 or p2' --basetemp=.cache/pytest-P2-sdk --junitxml=reports/generated/P2-sdk-only-junit.xml
```

结果为 160 passed、57 deselected；环境中根本未安装 FastAPI/LangGraph/LangChain/演示包，
Mock Adapter 的子进程也在该环境中实际执行并验证输出。此 160 项是累计测试的子集，
不重复加到 219 的总数中；deselected 不是 skipped 或真实 API 实验。

包含旧阶段的正式验收命令：

```powershell
.\.cache\p1-verify313\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.cache\p1-verify313\Scripts\python.exe scripts/check_phase.py P2
```

脚本实际运行六步（完整 cwd/argv 在机器 JSON 内）：

```powershell
# cwd: D:\Projects\Work\competition3
D:\Projects\Work\competition3\.cache\p1-verify313\Scripts\python.exe -m pip check
D:\Projects\Work\competition3\.cache\p1-verify313\Scripts\python.exe -m ruff check .
D:\Projects\Work\competition3\.cache\p1-verify313\Scripts\python.exe -m ruff format --check .
D:\Projects\Work\competition3\.cache\p1-verify313\Scripts\python.exe -m pytest -m 'p0 or p1 or p2' --basetemp=.cache/pytest-P2 --junitxml=D:\Projects\Work\competition3\reports\generated\P2-python-junit.xml
# cwd: D:\Projects\Work\competition3\apps\web
& 'C:\Program Files\nodejs\npm.cmd' run test
& 'C:\Program Files\nodejs\npm.cmd' run build
```

开发中还实际执行以下排查命令；它们不替代最终机器结果：

```powershell
.\.venv\Scripts\python.exe -m ruff check --fix .
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.venv\Scripts\python.exe -m pytest -m 'p0 or p1 or p2' --basetemp=.cache/pytest-P2-dev -x --tb=short --junitxml=reports/generated/P2-development-junit.xml
.\.venv\Scripts\python.exe -m pytest -m 'p0 or p1 or p2' --basetemp=.cache/pytest-P2-dev --tb=short --junitxml=reports/generated/P2-development-junit.xml
```

pytest 自动移除 Key/Token 等凭据，网络拒绝规则和普通回环拒绝保持；只允许 Windows
标准库 socketpair 的本地 IPC。独立真实脚本需要显式 --enable-real-api，不被阶段脚本调用。
本轮普通沙箱启动仍报 setup refresh 错误，命令经工具授权运行，项目路径未向父目录扩展。

## 真实测试统计

| 范围 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| P0 Python 回归 | 34 | 0 | 0 | 0 |
| P1 Python 回归（含新真实脚本的离线开关测试） | 57 | 0 | 0 | 0 |
| P2 上下文来源、冻结、JSON 伪造与错误脱敏 | 17 | 0 | 0 | 0 |
| P2 调用/结果/决策关联和变更后重验 | 18 | 0 | 0 | 0 |
| P2 决策/发现、Gate 动作适用和显式替换内容 | 34 | 0 | 0 | 0 |
| P2 事件往返、必填/版本/类型/JSON/截断限制 | 55 | 0 | 0 | 0 |
| P2 Protocol 与无框架 Mock Adapter | 2 | 0 | 0 | 0 |
| P0 前端回归 | 2 | 0 | 0 | 0 |
| **合计** | **219** | **0** | **0** | **0** |

pip check、Ruff lint/format、npm build 全部退出 0，38 个 Python 文件格式检查通过。
这些步骤不额外计为测试用例；前端仍是 P0 空应用，没有新增 Web 功能。

## 发现的问题和修复

1. 首次 P2 pytest 收集 211 项，在 74 passed / 1 failed 后由 -x 停止，其余未执行。
   失败用例发现：联合事件 TypeAdapter 的错误字符串仍包含合成敏感输入，模型自身的
   hide_input_in_errors 配置没有自动作用于 Union 适配器。为适配器显式配置该选项后，
   原失败测试保留，211 项全部通过。没有真实密钥进入这些测试输入或错误日志。
2. 增加变更后重验检查：现有模型可能持有可变 JSON，不能先 model_dump_json 再验证，
   因为这会把 NaN 转成 null、bytes 转成文本。改为直接读取原始字段再验证，并新增 5 项
   事件/决策变更与未校验 model_copy 的拒绝测试，累计 216 项通过。
3. 来源字段补充拒绝纯空白，增加 1 项用例，最终为 217 Python + 2 Web 通过。
4. 首轮 Ruff 报导入排序、长行和 UP038 风格问题；通过排序、格式化、拆分内嵌代码长行
   及使用 str | bytes 修复。最终 lint/format 均通过，没有禁用规则或删除断言。

所有失败均先修复当前阶段，再运行回归；没有用跳过或 Mock 输出掩盖真实结果。
P2 Mock Adapter/插件仅验证契约；真实模型的两次调用在独立 P1 记录中明确区分。

## 人工核对与安全不变量

- 公共 JSON Schema 已检查：联合事件 discriminator 有且仅有三种映射；SecurityContext
  schema 不包含私有来源标记；决策 schema 的 action/gate/reason_codes 均必填。
- SDK 默认依赖、静态源导入、隔离子进程和全新无 Agent 环境均验证无框架耦合。
- 模型自报 user_id/permissions/trusted 只能留在低信任参数中，不修改可信上下文；直接
  JSON/普通构造、伪造 validation context、未校验 model_construct 均不能取得来源标记。
- 冻结的权限/资源/预算不支持 model_copy(update=...) 提权；受信存储恢复要由后端重建。
- 策略与授权不来自模型分数：P2 未实现评分/策略引擎，也不接受额外 risk_score 字段，
  但“硬拒绝优先”等执行行为仍留给 P3，不能写成已验证执行保护。
- Gate BLOCK/REVIEW 零工具副作用、Gate 2 不向 LLM 传原文、审批/并发/重放等运行时
  安全不变量：**未实现/未验证**。本阶段没有受保护的真实工具路径。

## 未验证能力与已知风险

- Context 后端入口是应用信任边界，不是认证、签名或 Python 任意代码沙箱。调用方不能
  把不可信请求/模型 JSON 直接交给 from_backend；后端身份认证和上下文选择仍需业务保证。
- 关联只检查 ID/元数据摘要引用和上下文，不能证明来源或工具注册可信；不会验证真实
  摘要计算、完整参数 Schema 语义、执行授权、参数摘要绑定、防重放或预算核销。
- 模型字段冻结不使嵌套 payload 深度不可变；在解析/关联入口重验，真正执行点的再次
  校验与并发原子性属于 P3/P9。未经重验的 model_construct/model_copy 不能用于安全决策。
- repr 和错误字符串隐藏内容不等于通用脱敏；结构化 errors() 须 include_input=False，
  传输序列化仍包含 payload。P2 无密钥检测/Redactor/审计存储，不得记录原始敏感事件。
- 真实 DeepSeek 只验证一条正常只读样例，不覆盖异常、并发或防护效果；费用未计算，
  实验上限也不是账户账单保证。真实 API 不参与本阶段离线验收。
- AgentDojo、InjecAgent、MSB、τ³-bench 均未接入/运行，没有任何 Benchmark 成绩。
- 仅 Windows + Python 3.13.9 实测；Python 3.11/3.12、Linux/macOS 未实测。
  初次依赖获取仍需网络，Python 依赖锁目前没有 wheel 哈希。
- P1 的内存会话/无认证/节点级流式与工具自身沙箱局限仍保持，P2 未改造为生产系统。

## 停止点

P2 必需行为、安全/接口测试、P0/P1 回归和无 Agent 安装验证全部通过，范围内无阻塞
遗留问题。P1 已完成本地 Git 提交；P2 修改留待用户检查，尚未提交/推送。
本轮到 P2 停止，不进入 P3；等待用户明确授权下一阶段。
