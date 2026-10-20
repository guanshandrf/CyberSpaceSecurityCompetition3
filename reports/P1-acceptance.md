# P1 验收报告

- 阶段编号：P1 — 无 Guard 的基础 LangGraph Agent + DeepSeek 接口。
- 日期：2026-10-19（Asia/Shanghai）；正式验收完成于 20:38:31。
- 结论：**PASS，仅限 P1 离线基线验收**。SDK Guard 和 P2 及以后阶段均未实现。
- 最终自动化测试：**通过 92 / 失败 0 / 错误 0 / 跳过 0**。
- 机器结果：`reports/generated/P1-results.json`，时间戳
  `2026-10-19T12:38:31.964709+00:00`；对应 Python/Web JUnit 和六步日志在同目录。
- 真实 DeepSeek API：**未运行、未验证**。四项 Benchmark：**均未运行、未接入**。

## 目标与完成情况

| P1 验收项 | 实现和证据 |
| --- | --- |
| LangGraph + LangChain 基线 | 独立 agentguard-demo 0.1.0，真实 StateGraph(MessagesState) 执行 model → tools → model；不 import SDK |
| 默认 Fake Provider | 确定性回显、recall、多轮上下文与 JSON 工具命令；无 Key、无外网运行 |
| 真实 DeepSeek 接口 | 自定义 LangChain BaseChatModel，固定兼容聊天端点/模型，显式启用、服务端密钥、超时/调用/token 上限；协议由离线 HTTPX MockTransport 验证，真实 API 未验证 |
| 两种工具 | read_file 限只读 input 沙箱，write_note 限会话 notes 子目录；路径/大小/链接检查及独占创建，测试实际检查文件副作用 |
| 会话和聊天接口 | FastAPI 会话创建/计数查询、JSON 聊天；两轮上下文连续，不同会话隔离 |
| SSE | 逐节点发送 session/tool_call/tool_result/message/error/done；会话/trace/调用关联；生成器测试验证调用事件在真实工具执行之前发出 |
| 默认关闭无 Guard 基线 | 未显式启用时会话/聊天返回 503，不创建沙箱或 Provider；明确标记 unprotected |
| P0 回归与独立性 | 新环境先仅安装 SDK/开发依赖，确认没有 FastAPI/LangGraph/演示包，完成 P0 34 Python + 2 Web 回归，再离线安装演示包完成 P1 |

本轮未改动 `src/agentguard` 的任何实现。没有创建 SecurityEvent、SecurityContext、
SecurityDecision、Gate、Policy、Guarded Executor 或 LangGraph 安全 Adapter。
P1 传输事件和应用请求/配置模型不是 P2 的 SDK 安全契约。

## 初始状态和变更文件

初始 Git 状态干净，位于 main，已有 P0 提交 `03e24f39de787e6e0d116ed4c8501602ee22dfe5`。
已读取根计划、AGENTS 和架构/契约/威胁模型；项目文件操作限定本仓库。
P0 已有 34 Python + 2 前端测试；本轮新增 56 项 P1 Python 用例。

新增：

- `apps/api/pyproject.toml` 与 `apps/api/src/agentguard_demo/` 下的
  `__init__.py`、`settings.py`、`providers.py`、`tools.py`、`service.py`、`api.py`。
- `requirements-demo.in`、`requirements-demo.lock`：演示依赖独立管理，包含原开发锁文件
  和 39 项演示直接/传递依赖；Pydantic 等公共依赖不重复进入默认 SDK 的框架依赖。
- `tests/p1/conftest.py`、`test_api.py`、`test_dependencies.py`、`test_providers.py`、`test_sandbox.py`。
- 本报告及本地 `reports/generated/P1-*` 执行证据（generated 默认忽略）。

修改：

- `.env.example`、`README.md`、`apps/api/README.md`、`configs/README.md`、`fixtures/README.md`。
- `docs/architecture.md`、`docs/contracts.md`、`docs/threat-model.md`：记录当前实际路径与未实现范围。
- `requirements-dev.lock`：typing-extensions 4.15.0 → 4.16.0，满足 AnyIO 要求。
- `pyproject.toml`：新增 p1 标记、调整仓库内临时/缓存目录。
- `scripts/check_phase.py`：支持 P0/P1；P1 包含 P0 回归；分阶段 JSON/JUnit/日志，拒绝 P2+。
- `apps/web/vite.config.js`：仅按阶段输出 JUnit；没有开发 Web 聊天页面。
- `tests/conftest.py`：保留网络拒绝/凭据清理，允许 Windows 标准库 socketpair 所需本地 IPC。
- `tests/unit/test_phase_runner.py`：越阶段拒绝参数由 P1 改为 P2，因为 P1 已获授权；保留原测试目的。

## 执行环境与准确命令

全部项目命令从 `D:\Projects\Work\competition3` 执行。Windows AMD64、Python 3.13.9、
pip 25.2、Pydantic 2.12.4、pytest 8.4.2、Ruff 0.12.0；LangGraph 1.2.16、
LangChain Core 1.6.12、FastAPI 0.147.0、Uvicorn 0.54.0、HTTPX 0.28.1。
Node.js 24.15.0、npm 11.12.1；前端依赖沿用 P0 锁文件。

开发环境最初执行过以下依赖准备命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pip --isolated install --index-url https://pypi.org/simple --disable-pip-version-check --no-cache-dir --use-deprecated=legacy-resolver -r requirements-demo.in
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels typing-extensions==4.16.0
.\.venv\Scripts\python.exe -m pip uninstall -y langchain-openai openai jiter tiktoken regex
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps -e apps/api
.\.venv\Scripts\python.exe -m pip check
```

初版输入曾包含 langchain-openai；最终采用计划允许的自定义 Provider，移除上述不再需要的
客户端包并精确锁定最终依赖。初次 pip check 有版本冲突，修复后通过；详见问题记录。
锁文件来自最终安装分发元数据，最终干净安装使用正常解析器检查兼容性，不依赖 legacy
解析器放过冲突。

最终 wheel 准备、全新环境安装和验收命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pip --isolated download --index-url https://pypi.org/simple --disable-pip-version-check --no-cache-dir --only-binary=:all: --no-deps --use-deprecated=legacy-resolver --dest .cache/wheels -r requirements-demo.lock --retries 0 --timeout 20
.\.venv\Scripts\python.exe -m venv .cache/p1-verify313
.\.cache\p1-verify313\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-dev.lock
.\.cache\p1-verify313\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.cache\p1-verify313\Scripts\python.exe -I -c "import importlib.util; import agentguard; assert all(importlib.util.find_spec(n) is None for n in ['fastapi','langgraph','langchain_core','agentguard_demo']); print('SDK-only clean environment: PASS')"
.\.cache\p1-verify313\Scripts\python.exe scripts/check_phase.py P0
.\.cache\p1-verify313\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-demo.lock
.\.cache\p1-verify313\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps apps/api
.\.cache\p1-verify313\Scripts\python.exe scripts/check_phase.py P1
```

该新环境 `include-system-site-packages=false`；SDK 和演示包都是实际构建 wheel 后的普通
安装，没有使用 editable/PYTHONPATH 代替正式安装。缓存需先联网取得，安装和检查本身
均可离线。无缓存机器不能无网络首次安装。

P1 脚本的六个真实子命令如下；P0 同样运行，但标记为 p0、基准目录和结果前缀为 P0。
完整 argv/cwd/退出码/耗时在机器 JSON 内。

```powershell
# cwd: D:\Projects\Work\competition3
D:\Projects\Work\competition3\.cache\p1-verify313\Scripts\python.exe -m pip check
D:\Projects\Work\competition3\.cache\p1-verify313\Scripts\python.exe -m ruff check .
D:\Projects\Work\competition3\.cache\p1-verify313\Scripts\python.exe -m ruff format --check .
D:\Projects\Work\competition3\.cache\p1-verify313\Scripts\python.exe -m pytest -m 'p0 or p1' --basetemp=.cache/pytest-P1 --junitxml=D:\Projects\Work\competition3\reports\generated\P1-python-junit.xml
# cwd: D:\Projects\Work\competition3\apps\web
& 'C:\Program Files\nodejs\npm.cmd' run test
& 'C:\Program Files\nodejs\npm.cmd' run build
```

## 实际自动化统计

| 范围 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| P0 Python 回归 | 34 | 0 | 0 | 0 |
| P1 HTTP/SSE、上下文、开关、调用上限、错误处理、本地 IPC | 18 | 0 | 0 | 0 |
| P1 独立依赖及基线不依赖 SDK | 2 | 0 | 0 | 0 |
| P1 Provider/Fake/DeepSeek 离线协议与配置 | 11 | 0 | 0 | 0 |
| P1 沙箱读写、越界、大小、真实目录联接/硬链接 | 25 | 0 | 0 | 0 |
| 前端 P0 回归 | 2 | 0 | 0 | 0 |
| **合计** | **92** | **0** | **0** | **0** |

`pip check`、Ruff lint、Ruff format、前端 build 全部退出 0，未另计为测试用例。
先于演示依赖安装的 P0 独立验收为 34 Python + 2 Web 通过，见
`reports/generated/P0-results.json`，时间 `2026-10-19T12:38:06.972313+00:00`。
这 36 项属于回归的重复执行，不叠加到 92 项中；p1 用例在 P0 运行中是 deselected，
不是跳过真实 API。原 P0 Markdown 报告作为历史记录保留，本次生成 JSON 是新的回归证据。

## 本地实际服务冒烟（Fake）

除了 TestClient，还用普通安装的验证环境实际启动 Uvicorn，显式载入仓库内
`.cache/p1-smoke.env`。文件仅包含以下非秘密 Fake 配置：

```dotenv
AGENTGUARD_ENABLE_BASELINE=true
AGENTGUARD_LLM_PROVIDER=fake
AGENTGUARD_ENABLE_REAL_API=false
AGENTGUARD_SANDBOX_ROOT=.cache/p1-http-smoke
AGENTGUARD_MAX_PROVIDER_CALLS=4
AGENTGUARD_MAX_TOTAL_PROVIDER_CALLS=4
AGENTGUARD_MAX_TOKENS=16
```

在 `.cache/p1-http-smoke/input/hello.txt` 放入公开受控文本
`P1 local HTTP smoke fixture`；启动前移除该子进程的 baseline/provider/real_api/密钥环境变量：

```powershell
$env:AGENTGUARD_ENABLE_BASELINE=$null
$env:AGENTGUARD_LLM_PROVIDER=$null
$env:AGENTGUARD_ENABLE_REAL_API=$null
$env:DEEPSEEK_API_KEY=$null
.\.cache\p1-verify313\Scripts\python.exe -m uvicorn agentguard_demo.api:app --host 127.0.0.1 --port 0 --env-file .cache/p1-smoke.env
```

实际分配端口 9514。随后执行以下 PowerShell 请求并断言返回内容及计数：

```powershell
$taskBase='http://127.0.0.1:9514'
$taskHealth=Invoke-RestMethod -Uri ($taskBase+'/health')
$taskSession=Invoke-RestMethod -Method Post -Uri ($taskBase+'/sessions')
$taskReadBody=@{message='read_file {"path":"hello.txt"}'} | ConvertTo-Json
$taskRead=Invoke-RestMethod -Method Post -Uri ($taskBase+'/sessions/'+$taskSession.session_id+'/chat') -ContentType application/json -Body $taskReadBody
$taskWriteBody=@{message='write_note {"name":"http-note.txt","content":"local-only"}'} | ConvertTo-Json
$taskStream=Invoke-WebRequest -UseBasicParsing -Method Post -Uri ($taskBase+'/sessions/'+$taskSession.session_id+'/stream') -ContentType application/json -Body $taskWriteBody
$taskInfo=Invoke-RestMethod -Uri ($taskBase+'/sessions/'+$taskSession.session_id)
```

结果：health 200、session 201、chat 200、SSE 200、会话查询 200；读取内容正确，SSE 含
tool_call/tool_result/done(ok=true)，会话 turns=2、provider_calls=4。记录保存在
`reports/generated/P1-local-http-smoke.log`。服务验证后停止。此项是本地 Fake HTTP 验证，
没有调用外网、不计入真实 DeepSeek，也不额外增加自动化用例数。

## 发现的问题与修复

1. **依赖冲突**：初次安装 AnyIO 4.15.1 后 pip check 返回失败，要求
   typing-extensions>=4.16.0。升级开发锁中的该版本，随后开发环境和干净环境的正常安装/
   pip check 都通过。没有降低版本检查或把安装警告当作通过。
2. **旧缓存 ACL**：首次收集 87 项测试，但临时目录 fixture 无法访问旧 `.cache/pytest`；
   pytest 收尾也无法写旧 `.pytest_cache`。该次运行没有完整可信汇总，不计为通过。
   改用仓库内新的、分阶段临时目录和缓存目录；保留旧目录，未进行危险清理或修改权限树。
3. **离线拦截与 asyncio**：改用新缓存后为 1 通过、1 setup error（-x 停止），
   Windows asyncio 的 socketpair 回环 IPC 被原网络拦截阻断，继而产生未关闭 loop 警告。
   仅允许调用栈确认为标准库 socketpair 的本地连接；普通回环、DNS、connect_ex 和外网
   仍拒绝，新增实际 IPC/普通连接拒绝测试。未关闭 warnings-as-errors。
4. **换行差异**：环境修复后为 30 通过、1 失败（收集 88、-x 停止，其余未执行）。
   Windows 文本 fixture 使用 CRLF，工具返回未归一化。修复 read_file 在解码后将 CRLF/CR
   统一为 LF，保持源文件字节不变；原测试保留。后续 88 项通过，增加两项预算/流式行为
   测试后最终 90 Python + 2 Web 通过。
5. **Python 别名**：第一次尝试 `python -m venv .cache/p1-verify-venv` 时，授权进程 PATH
   中的 python 实为 3.10.11，低于项目 >=3.11 要求，无法使用 cp313 wheel，安装失败。
   明确改用已有 `.venv/Scripts/python.exe`（3.13.9）创建新的 p1-verify313，全部离线安装
   成功；旧失败环境留在忽略目录。3.10 不属于支持范围。
6. **静态检查**：首轮出现 1 条 E501 与 8 条 I001，拆分长行、整理导入并格式化修正；
   最终 26 个 Python 文件格式检查和 lint 通过，未禁用规则。

没有删除失败测试以粉饰结果。越阶段参数由 P1 更新为 P2 是授权范围变化所必需，
并非绕过失败；P2+ 仍被 CLI 拒绝。

## 安全不变量、未验证能力与风险

- SDK 不依赖 Web/Agent/Benchmark：**保持且已验证**；真实无框架环境可导入并完成 P0。
- 真实 API 开关/密钥要求、错误不泄漏、调用/token 限制：**离线测试通过**；真实 API
  连通性、账号额度、真实 token usage/费用和模型工具选择能力：**未验证**。
- Gate 1 BLOCK/REVIEW 零执行、可信 SecurityContext、Gate 2 结果审核等：**未实现/未验证**，
  P1 是显式隔离的无 Guard 基线，不能宣称任何工具经过 Guard 保护。
- read_file/write_note 自身沙箱限制：**受控 fixtures 实测通过**；包括本机真实 junction 和
  hardlink，但不构成防本机恶意进程竞态、恶意原生扩展或任意代码的 OS 沙箱。
- 接口仅供回环地址、本地单用户实验，无身份认证/多租户隔离；输入沙箱只能放公开受控数据。
  工具结果未经 Gate 2，提示注入仍可能影响此基线；没有 SDK 审计或审计脱敏能力。
- 会话在进程内存，重启丢失；每进程调用计数也会重置，不是账户费用上限。max_tokens 只
  限制输出，输入 tokens 仍可能计费。工具执行后的失败不回滚文件副作用。
- SSE 是节点流，不是逐 token 流；断连/重试恢复与并发异常的完整工程加固未在 P1 验证。
- DeepSeek 手动步骤已写入 `apps/api/README.md`，本轮未执行；MockTransport 用例是合成
  协议测试，不能当作真实模型成绩。四个 Benchmark 均无下载、无适配、无成绩。
- Python 3.11/3.12 与 Linux/macOS 未实测；本次仅 Windows + Python 3.13.9。版本锁没有
  Python wheel 哈希，初次取得依赖需网络，同平台离线重建已实测。
- 本轮普通沙箱命令启动持续报 setup refresh 错误，必要命令经工具授权运行；项目文件
  检查、写入和路径搜索均限定在当前仓库，未向父目录查找项目文件。

## 停止点

P1 必要离线验收与 P0 回归均通过，范围内没有阻塞问题。本轮到此停止，等待用户检查
并明确授权进入 P2；不会自动实施后续阶段。验收当时变更尚未提交或推送 GitHub；
后续 Git 提交及真实 API 补充验证另行记录。
