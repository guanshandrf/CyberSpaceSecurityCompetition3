# P6 安全审计修复验收

结论：**PASS**。日期：2026-10-21。范围仅为 P6 安全加固，未进入 P7，未提交或推送。
环境：Windows、Python 3.13.9、SDK 0.6.0 普通安装、LangGraph 1.2.16、LangChain Core 1.6.12。
SDK 版本号保持 0.6.0，修复前后以源码 SHA-256 区分；准确时间、命令和源文件摘要见机器证据。
本报告取代原 P6 报告中“无续期”和“非法调用直接中止”的当前能力描述；历史报告不改写。

## 一、根因与修复

### 1. 过期注册无法安全续期

根因：Adapter 只在初始化注册；注册 TTL 到期后 tools() 不再暴露工具，原包装也只能被拒绝。
没有由当前后端权限驱动的续期入口；注册表过期检查还会把原状态直接改成 BLOCK，不能可靠
区分过期与撤销。慢速 Gate0/审批完成时若不重验状态，还可能覆盖并发撤销。

修复：

- `src/agentguard/registry/tools.py:75` 新增 renew。内部读取原绑定和注册快照，校验预期摘要、
  版本及同会话身份；权限由本次当前可信上下文重新交给 Gate0 检查。续期生成新注册事件和
  新代次，不接受模型的 handler/版本替换，不直接延长过期时间。
- 同文件 `:112` 提取注册实现；`:185` 与 `:231` 在发布注册/审批状态前核对 CHECKING/
  APPROVING 状态，撤销/更新优先；`:242` 过期解析仅把 ALLOW 改为 EXPIRED，不抹掉撤销。
- `src/agentguard/adapters/langgraph.py:111` 新增后端 refresh_registrations；`:134` 提供撤销。
  只处理原先获准的过期注册，失败/REVIEW 保持拒绝；不重建 Executor，因此预算、审批绑定
  和防重放状态保持。invoke/tools 不自行续期，旧包装在未续期时仍拒绝执行。
- `apps/api/src/agentguard_demo/protected.py:88` 每轮从可信本地配置构造当前注册管理员上下文；
  `service.py:163` 在模型绑定前调用续期。撤销工具不能被下一轮自动恢复。

验证：长会话跨 TTL 成功、原摘要/身份/声明权限/版本保持、失败/权限不足/异常/审计故障/
REVIEW 零执行、过期后旧包装拒绝、并发仅续期一次、续期期间撤销优先、预算/防重放不重置。
过期测试通过控制单调时钟确定性推进，实际运行注册/执行代码，未声称等待真实五分钟。

### 2. 非法 Tool Call 缺少审计及协议恢复

根因：ToolCallEvent 验证前的异常直接抛 ValueError，没有 Gate1 拒绝审计；图只检查
tool_calls，忽略 invalid_tool_calls；异常会留下未配对 AI 调用，影响下一轮。单批处理也
缺少 ID 配对预检，可能在发现缺失/重复 ID 前已执行其他工具。

修复：

- `src/agentguard/adapters/langgraph.py:203` 对非法请求构造只用于拒绝的安全 envelope，
  输出 Gate1 BLOCK/event.invalid 审计。无原始参数、错误正文或不可信工具名；不把修补后
  envelope 送去执行。原 P2 Identifier 和事件协议未改变。
- 同文件 `:254` dispatch 为模型提供安全恢复入口；存在可配对 ID 时经过 ResultHandler/
  Gate2 返回固定错误 ToolMessage，并保持原始 ID。严格后端 invoke 仍审计后抛通用
  ValueError，原有拒绝测试保留，不把非法请求改成可执行请求。
- 同文件 `:287`、`:296` 批量预检缺失/重复/过长/不可 UTF-8 编码 ID；整批执行前拒绝。
  `:317` 节点同时处理 tool_calls/invalid_tool_calls，包装的同步/异步入口使用恢复通道。
- `src/agentguard/audit/store.py:77` 新增专用拒绝记录；原始 ID 即使不符合 P2 也只保留
  HMAC。有效 ID 的关联方式不变；审计故障中止且不回显异常正文。自定义仅 append 的
  sink 收到规范化 ID；要保留原始非法 ID 的同 sink HMAC 关联，可实现 append_invalid_call。
- `service.py:89` 在保存/流出模型消息前预检 ID；`:94` 保护工具节点使用批处理；`:223`
  清除失败或中断轮次的消息，防止未配对历史污染下一轮，Executor 状态不回滚。
  保护模式工具事件参数仍脱敏，未知名称使用固定标记。

验证：坏 JSON、NaN、额外上下文、非法类型/ID、审计失败、缺失/重复/不可编码 ID、混合批次、
并发非法/正常调用、实际 LangGraph 会话恢复；真实 handler 计数和文件副作用均检查。
可恢复调用一一配对；无法配对的调用没有伪造 ToolMessage，而是中止轮次并保留拒绝审计。

### 3. Gate2 对中英文改写的覆盖不足

根因：原规则主要检查少量指令覆盖/角色前缀/凭据外发短语，不能识别多种间接请求、
敏感文件目标、替代动作词和中文工具诱导，也缺少 Unicode 规范化。

修复：`src/agentguard/detectors/results.py:83`、`:103`、`:157` 在既有规则上增加 NFKC/
零宽字符规范化，组合请求语气、操作动作、敏感目标/外发目的地；补充角色/优先级伪装与
工具调用诱导。否定/研究引用的处理限定在分句，不能给后续独立恶意动作整篇豁免。
Detector 只返回 Finding，Gate2/Policy 仍负责决策，无外部模型、无新增运行依赖。

新增 `fixtures/p6-result-intents.json` 的人工对照语料：中英文各 12 恶意、12 正常，包含
相同敏感文件/凭据/角色/工具词汇的正常介绍、否定建议及研究引用；另测 Unicode、嵌套 JSON
与实际 LangGraph 的安全结果隔离。**这是组合意图规则增强，不是通用语义模型。**

| 专门针对已知漏检的对照集 | 修复前命中/恶意数 | 修复后命中/恶意数 | 修复前/后正常误报 |
| --- | ---: | ---: | ---: |
| 英文 | 0/12 | 12/12 | 0/12 → 0/12 |
| 中文 | 0/12 | 12/12 | 0/12 → 0/12 |

这不是独立评估集，不计算或宣称 Benchmark/真实模型防护成绩，不外推到任意语义改写。

## 二、修复前后同组测试

修复前保存 SDK/演示共 34 个 Python 源文件到 `.cache/p6-security-before`，逐文件 SHA-256
写入 `reports/generated/P6-security-before-source.json`，同时保留原 P6 验收统计。
旧快照通过独立进程 sys.path 显式选择，并断言实际导入位置；正式运行没有使用旧快照。

| 最终相同用例 | 修复前通过/失败 | 修复后通过/失败 | 错误/跳过（前后均） |
| --- | ---: | ---: | ---: |
| 注册/续期 | 0/11 | 11/0 | 0/0 |
| 非法调用/恢复 | 0/15 | 15/0 | 0/0 |
| 检测对照、编码变体、语料检查 | 25/28 | 53/0 | 0/0 |
| 改写注入的实际图闭环 | 0/2 | 2/0 | 0/0 |
| 合计 | 25/56 | 81/0 | 0/0 |

旧版本失败包括缺少新生命周期/恢复 API、没有拒绝审计、实际长会话失败及新增改写漏检；
不是所有失败都声称为原版本可执行越权。正常语料的 24 项及语料完整性 1 项原已通过。
修复后的 81 项取自正式全量 JUnit 的相同 classname/name，不重复加总测试数量。
对照与源码差异见 `reports/generated/P6-security-fix-comparison.json`。

最初 77 项开发用例在旧源码为 25 passed/52 failed；修复后 P4–P6 开发回归为
191 passed/0 failed。之后补充不可编码 ID 与两条实际图用例，最终以以上 81 项为准。

## 三、准确执行命令

所有项目命令工作目录为 `D:\Projects\Work\competition3`；默认 helper 启动失败时使用
工具审批机制执行同一仓库内命令，未改 ACL 或扩大项目文件访问边界。
未读取真实 .env，不输出/修改真实 Key。格式化阶段发现的导入/长行问题已修复。

开发检查及实际安装：

```powershell
.\.venv\Scripts\python.exe -m ruff check . --fix
.\.venv\Scripts\python.exe -m ruff format .
New-Item -ItemType Directory -Force .cache/p6-security-install-temp | Out-Null
$env:TEMP=(Join-Path (Get-Location) '.cache/p6-security-install-temp')
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps . apps/api
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest tests/p6 tests/p4 tests/p5 -m 'p4 or p5 or p6' --basetemp=.cache/pytest-P6-security-dev1 --tb=short --junitxml=reports/generated/P6-security-dev1-junit.xml
```

最终旧版本对照命令（预期退出 1，不是验收失败；JUnit 必须确实生成）：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
@'
from pathlib import Path
import sys
root=Path.cwd()
sys.path.insert(0,str(root/'.cache/p6-security-before/demo'))
sys.path.insert(0,str(root/'.cache/p6-security-before/sdk'))
import agentguard,agentguard_demo,pytest
assert Path(agentguard.__file__).is_relative_to(root/'.cache/p6-security-before/sdk')
assert Path(agentguard_demo.__file__).is_relative_to(root/'.cache/p6-security-before/demo')
raise SystemExit(pytest.main(['tests/p6/test_security_renewal.py','tests/p6/test_security_invalid_calls.py','tests/p6/test_result_intents.py','tests/p6/test_adapter.py::test_paraphrased_injection_is_blocked_in_real_graph','--basetemp=.cache/pytest-P6-security-before-final','--tb=no','-q','--junitxml=reports/generated/P6-security-before-final-junit.xml']))
'@ | .\.venv\Scripts\python.exe - | Tee-Object reports/generated/P6-security-before-final.log
```

最终源码普通安装后，使用原正式入口：

```powershell
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps . apps/api
.\.venv\Scripts\python.exe scripts/check_phase.py P6
```

正式入口实际运行六步，全部退出 0：

| 工作目录 | 命令（python 为主 .venv 解释器） |
| --- | --- |
| 根目录 | `python -m pip check` |
| 根目录 | `python -m ruff check .` |
| 根目录 | `python -m ruff format --check .` |
| 根目录 | `python -m pytest -m 'p0 or p1 or p2 or p3 or p4 or p5 or p6' --basetemp=.cache/pytest-P6 --junitxml=D:\Projects\Work\competition3\reports\generated\P6-python-junit.xml` |
| apps/web | `npm.cmd run test` |
| apps/web | `npm.cmd run build` |

| 正式累计 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| P0 | 34 | 0 | 0 | 0 |
| P1 | 57 | 0 | 0 | 0 |
| P2 | 126 | 0 | 0 | 0 |
| P3 含加固 | 186 | 0 | 0 | 0 |
| P4 | 47 | 0 | 0 | 0 |
| P5 | 29 | 0 | 0 | 0 |
| P6（原 38 + 新 81） | 119 | 0 | 0 | 0 |
| Web | 2 | 0 | 0 | 0 |
| 合计 | 600 | 0 | 0 | 0 |

独立 SDK 新环境安装与测试（不是复用已安装框架的主环境）：

```powershell
.\.venv\Scripts\python.exe -m venv .cache/p6-security-sdk-venv
.\.cache\p6-security-sdk-venv\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-dev.lock
.\.cache\p6-security-sdk-venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.cache\p6-security-sdk-venv\Scripts\python.exe -I -c "import importlib.util as u; import json; from pathlib import Path; import agentguard, agentguard.contracts, agentguard.gates, agentguard.executor, agentguard.registry, agentguard.adapters; absent={x:u.find_spec(x) is None for x in ['langgraph','langchain_core','fastapi','agentguard_demo']}; assert all(absent.values()); report={'sdk_version':agentguard.__version__,'frameworks_absent':absent,'conclusion':'PASS'}; Path('reports/generated/P6-security-sdk-isolation.json').write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report))"
.\.cache\p6-security-sdk-venv\Scripts\python.exe -m pip check
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.cache\p6-security-sdk-venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/security tests/p2 tests/p3 tests/p4 tests/p5 tests/p6/test_result_intents.py --basetemp=.cache/pytest-P6-security-sdk -o cache_dir=.cache/pytest-cache-P6-security-sdk --junitxml=reports/generated/P6-security-sdk-junit.xml
```

结果：导入/框架缺席断言成功，pip check 退出 0，**475 passed/0 failed/errors/skipped**。
按明确文件路径选择 SDK 范围，所有框架测试已在主环境全量执行，没有跳过安全测试。
475 项与正式累计重叠，不重复计入 600。

## 四、证据、工程边界与遗留风险

实际运行代码仅修改六个文件：Adapter、注册表、审计、结果 Detector、演示 protected/service。
新增三个测试文件和对照 JSON，原 test_adapter.py 只新增两条用例；conftest.py 增加可选 Gate0
注入参数。原安全测试未删除、未跳过、未弱化。文档同步 gate0/gate2/langgraph/架构/威胁模型。
没有新增 SDK 核心框架依赖，P2 contracts 全部源文件 SHA-256 与旧快照相同。
Gate1/Executor/Policy 的原安全实现未修改，硬拒绝、审批零副作用、预算/防重放全量回归通过。

证据均在 reports/generated：

- P6-security-before-source.json、P6-security-before-final-junit.xml/.log：旧源码与复现。
- P6-results.json、P6-python-junit.xml、P6-web-junit.xml、六步日志：本次正式全量结果。
- P6-security-sdk-junit.xml、P6-security-sdk-isolation.json：独立 SDK 验证。
- P6-security-fix-comparison.json、P6-security-fix-results.json：同组对照和最终汇总。
- `git diff --check` 实际退出 0。

限制和未验证项：

1. 检测仍是有限组合规则；对照样本专门覆盖已知缺陷，不能证明任意语言/语义/编码的泛化。
   跨文段指代、隐喻、伪装研究引用可能漏报，操作文档可能误报，不能宣称消除提示注入。
2. SDK 续期必须由可信后端显式传入当前注册权限。演示每轮从本地配置构造管理员，并没有
   新建身份认证/多租户权限系统。自定义接入必须正确更新真实后端权限；失败/REVIEW 不自动重试放行。
3. 无法配对的调用只能中止轮次；中断历史清理不是工具事务，已产生副作用不能回滚。
   预算/防重放保持单实例单进程，重启和分布式核销仍无保证。
4. 只保护 Adapter 接管工具；恶意 Python 代码、额外原始 ToolNode、框架内置/托管工具仍不在范围。
5. 本次真实 DeepSeek、外部模型、所有 Benchmark：**NOT_RUN**。Fake/受控时钟/隔离 fixtures
   均明确为离线测试手段。没有人工浏览器验证；实际使用 LangGraph、FastAPI 既有回归、
   文件副作用和 SQLite。其他 OS/Python 版本未验证。

三个审计问题已按本轮范围修复，必要测试和原阶段回归全部通过，结论 PASS。
本轮到此停止，等待用户审阅；不进入 P7，不自动提交/推送，也不改写旧审计 ZIP。
