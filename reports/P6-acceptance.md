# P6 验收报告：LangGraph Adapter 与安全闭环

结论：**PASS**。正式验收完成于 2026-10-21 18:40:47（Asia/Shanghai），
Windows、Python 3.13.9、SDK 0.6.0、LangGraph 1.2.16、LangChain Core 1.6.12。
依据用户连续执行 P4–P6 的授权，先补录已有 P5 PASS 报告，再实施 P6；本阶段结束后停止。

## 完成内容和验收依据

| 要求 | 实际实现与证据 |
| --- | --- |
| 可用 Adapter/protect 门面 | LangGraphAdapter 与 protect(bindings, ...)，提供模型工具包装和 StateGraph 工具节点，测试中实际编译、运行 LangGraph |
| 注册/调用/结果规范化 | 初始化注册经过 Gate0；框架调用变成 ToolCallEvent；正常/异常/未执行/非法输出统一经过 ResultHandler 和 Gate2 |
| 强制执行 | 只绑定 Gate0 获准包装，严格 registry 模式 Executor 核销；不将原始 SandboxTools.as_tools 放入保护图 |
| baseline/protected 合法任务 | 两种配置实际完成沙箱读、写及多轮历史；基线在阻止 SDK 导入的子进程中仍实际创建笔记 |
| 零副作用 | 权限拒绝、Schema/未知工具、未批准 REVIEW、注册拒绝/过期及检测期间撤权均验证真实 handler 执行计数为零 |
| 安全结果 | 实际记录 Fake 模型收到的 ToolMessage：BLOCK 无恶意原文，SANITIZE 仅替换内容；工具异常/结果检查异常/非法输出不回退原文 |
| trace/并发 | 原始 tool_call_id 保留；同轮多调用共享 trace、不同 call ID；跨轮保持预算；并发重复调用仅执行一次，并发 8 次不超过预算 3 |
| 三 Gate 可观察 | SQLiteAudit 实际存储 Gate0/1/2 白名单审计，调用与结果 HMAC 关联一致，不记录敏感原文 |
| 可选依赖 | 核心仅 Pydantic，框架 extra 隔离；纯 SDK 新环境实际安装并运行核心回归 |

P2 统一事件协议与公共接口未修改。没有实施 P7 Web/审计 API、P8 Benchmark 或其他后续功能。

## 修改文件及关键位置

- `src/agentguard/adapters/langgraph.py:18`：只有元数据/受控回调的框架包装，同步/异步/直接调用走同一通道。
- 同文件 `:38`：会话 Adapter；`:93` 后端撤权；`:112` 事件归一化；`:137` 执行与安全结果；
  `:153` 已批准工具集合；`:168` StateGraph 节点；`:182` protect 门面。
- `apps/api/src/agentguard_demo/protected.py:12`：公共 SDK 接入、可信会话上下文、路径包装；
  `:80` 审计目标路径及硬链接检查。SDK 传入规范绝对路径，后端转回相对路径后调用原沙箱工具。
- `apps/api/src/agentguard_demo/service.py:57`、`:123`：保留图循环和节点流；保护模式独占工具路径，
  按会话复用 Adapter；tool_call 参数展示脱敏，只输出安全工具结果。
- `settings.py:14`、`:27`、`api.py`、`providers.py`：后端保护开关、互斥模式和 Provider 启用；
  默认两模式关闭，请求不能指定配置/权限/凭据。
- `tests/p6/conftest.py`、`test_adapter.py`、`test_demo.py`：新增 38 项真实本地行为测试。
- `tests/p1/test_dependencies.py`：保留基线独立性要求；允许仅保护集成文件导入公共 SDK，
  增加阻止 SDK 导入的基线实际写入验证，没有删除旧安全要求。
- `tests/unit/test_package.py`：显式加载可选 Adapter 后的模块边界断言；P0 隔离导入仍拒绝框架。
- `pyproject.toml`、公共版本、演示可选 guard extra、阶段 runner/marker、Web JUnit 前缀、
  offline fixtures、`.env.example` 及 README/架构/契约/威胁模型/`docs/langgraph.md` 同步更新。

## 实际命令与结果

所有项目命令工作目录为 `D:\Projects\Work\competition3`。
默认命令启动曾在执行前报 helper setup 错误；采用工具审批机制执行同一仓库内命令，
没有修改底层沙箱权限、ACL 或向父目录查找项目文件。安装后续临时目录显式放入仓库 .cache。

开发首轮（新增 P6 初版 34 项加 P1 57 项）：

```powershell
.\.venv\Scripts\python.exe -m ruff check . --fix
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps . apps/api
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -m 'p1 or p6' --basetemp=.cache/pytest-P6-dev1 --junitxml=reports/generated/P6-dev1-junit.xml
```

结果：91 passed，0 failed/errors/skipped，422 deselected。初期 Ruff 有长行/导入问题，
经格式化与导入整理修复；没有删改失败测试掩盖问题。随后增加上下文、多工具、依赖及审计链接测试。

最终安装和纯 SDK 新环境准备（实际执行，离线本地 wheels）：

```powershell
New-Item -ItemType Directory -Force .cache/p6-install-temp | Out-Null
$env:TEMP=(Join-Path (Get-Location) '.cache/p6-install-temp')
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m ruff check . --fix
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps . apps/api
.\.venv\Scripts\python.exe -m venv .cache/p6-sdk-venv
.\.cache\p6-sdk-venv\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-dev.lock
.\.cache\p6-sdk-venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.venv\Scripts\python.exe scripts/check_phase.py P6
```

正式入口的六步及退出码如下；完整 argv/cwd/耗时见 `reports/generated/P6-results.json`：

| 工作目录 | 实际命令（python 为主 .venv 解释器） | 退出码 |
| --- | --- | ---: |
| 根目录 | `python -m pip check` | 0 |
| 根目录 | `python -m ruff check .` | 0 |
| 根目录 | `python -m ruff format --check .` | 0 |
| 根目录 | `python -m pytest -m 'p0 or p1 or p2 or p3 or p4 or p5 or p6' --basetemp=.cache/pytest-P6 --junitxml=D:\Projects\Work\competition3\reports\generated\P6-python-junit.xml` | 0 |
| apps/web | `npm.cmd run test` | 0 |
| apps/web | `npm.cmd run build` | 0 |

| 正式累计范围 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| P0 | 34 | 0 | 0 | 0 |
| P1 | 57 | 0 | 0 | 0 |
| P2 | 126 | 0 | 0 | 0 |
| P3（含安全加固） | 186 | 0 | 0 | 0 |
| P4 | 47 | 0 | 0 | 0 |
| P5 | 29 | 0 | 0 | 0 |
| P6 | 38 | 0 | 0 | 0 |
| Web | 2 | 0 | 0 | 0 |
| 合计 | 519 | 0 | 0 | 0 |

## 独立 SDK 安装验证

新环境仅安装 requirements-dev.lock 和 SDK 普通安装，未安装演示包/框架。
实际执行以下隔离解释器断言（结果同时写入 JSON）：

```powershell
.\.cache\p6-sdk-venv\Scripts\python.exe -I -c "import importlib.util as u; import json; from pathlib import Path; from importlib.metadata import version; import agentguard; import agentguard.contracts, agentguard.gates, agentguard.executor, agentguard.registry, agentguard.adapters; forbidden=['langgraph','langchain_core','fastapi','agentguard_demo']; absent={x:u.find_spec(x) is None for x in forbidden}; assert all(absent.values()), absent; assert version('agentguard')=='0.6.0'; report={'sdk_version':version('agentguard'),'frameworks_absent':absent,'conclusion':'PASS'}; Path('reports/generated/P6-sdk-isolation.json').write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report))"
.\.cache\p6-sdk-venv\Scripts\python.exe -m pip check
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.cache\p6-sdk-venv\Scripts\python.exe -m pytest -m 'p0 or p2 or p3 or p4 or p5' --basetemp=.cache/pytest-P6-sdk -o cache_dir=.cache/pytest-cache-p6-sdk --junitxml=reports/generated/P6-sdk-junit.xml
```

断言与 pip check 均成功；**422 passed，0 failed/errors/skipped，95 deselected**。
95 项为 P1/P6 框架测试，已由正式主环境全部执行；这里是按独立 SDK 范围选择，并非跳过安全测试。
422 与正式累计中的核心测试重叠，不重复计入 519 项。

证据：P6-results.json、P6-python-junit.xml、P6-web-junit.xml、六步日志、
P6-sdk-junit.xml、P6-sdk-isolation.json（均在 reports/generated）。
`git diff --check` 退出 0；Git 的 LF/CRLF 提示不影响结果。人工浏览器交互未执行，
API/SSE 通过真实 FastAPI TestClient 验证，文件读写/SQLite/LangGraph 均实际运行。

## 安全不变量、限制与停止点

硬性拒绝优先、BLOCK/REVIEW 零副作用、审批/预算/防重放、撤权重验、Gate2 原文隔离与
审计脱敏均保持；旧阶段全量回归通过。包装同步/异步入口、并发预算及撤权竞态也通过。

限制：规则检测并不完备，Gate2 不能撤销工具副作用；路径检查不能隔离恶意本机进程。
任意 Python handler/插件/后端受信；本封装不能防止受信代码反射或自行保存原始引用。
框架内置/托管工具、子 Agent、额外原始 ToolNode 不在保护范围。演示无认证、审批 UI、
会话持久化；只能本地单用户实验。TTL 默认 300 秒，到期安全拒绝，门面未提供热更新管理。
预算/重放/注册表为单实例单进程，不提供重启和多进程保证。

本阶段真实 DeepSeek：**NOT_RUN**；所有 Benchmark：**NOT_RUN**。
Fake 为离线测试模型，未被冒充真实外部验证；历史 P1 冒烟不证明本阶段保护效果。
其他 OS/Python 版本未验证。本阶段必要离线行为和依赖边界满足验收，因此 PASS。

P4–P6 连续任务已完成，具备申请 P7 的阶段条件；**尚未获 P7 授权，不进入 P7**。
没有创建 Git 提交、标签或推送，保留原有未提交工作，停止等待用户审阅。
