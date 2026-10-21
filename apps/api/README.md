# 本地 LangGraph 演示：独立基线与 P6 保护模式

此包 `agentguard-demo` 的基线独立于 SDK；保护模式惰性加载公共 SDK Adapter。真实 LangGraph 的
`StateGraph(MessagesState)` 执行 `model → tools → model` 循环，FakeChatModel 和
DeepSeekChatModel 都使用 LangChain BaseChatModel 接口。基线工具只具备自身目录约束；
保护模式通过 Gate0 注册、Gate1/Executor 和 Gate2 闭环，详见 `docs/langgraph.md`。

保护模式在同一依赖环境和 SDK 安装后，设置 AGENTGUARD_ENABLE_BASELINE=false、
AGENTGUARD_ENABLE_PROTECTION=true。两模式互斥且默认均关闭，只允许可信后端设置。
模型绑定和工具节点仅持有受保护包装，原 SandboxTools.as_tools 不进入保护图。
保护模式 /health 返回 guard=enabled，/sessions 返回 mode=protected；工具事件参数
脱敏为 [REDACTED]，工具结果只包含 Gate2 安全内容。audit.sqlite 保存三个 Gate 的脱敏审计，
P7 另提供安全审计 API/UI，见根目录 `docs/web-chat.md`。下述 unprotected 格式专指基线。

## 安装和 Fake 启动

所有命令在项目根目录执行，安装步骤见根 README 的 P1 部分。服务只绑定本地回环：

```powershell
$env:AGENTGUARD_ENABLE_BASELINE='true'
$env:AGENTGUARD_LLM_PROVIDER='fake'
$env:AGENTGUARD_ENABLE_REAL_API='false'
.\.venv\Scripts\python.exe -m uvicorn agentguard_demo.api:app --host 127.0.0.1 --port 8000
```

两种模式都未设置时 `/health` 可访问，会话和聊天均返回 503。默认不会读取 `.env`、
创建沙箱或构造网络模型。`.env` 只有通过 `--env-file .env` 明确指定才加载。

## 接口与示例

| 方法/路径 | 输入/输出 |
| --- | --- |
| GET `/health` | baseline_enabled、guard=not_implemented；不返回凭据 |
| POST `/sessions` | 创建随机 session_id；mode=unprotected |
| GET `/sessions/{id}` | 会话轮数、Provider 调用数；不存在返回 404 |
| POST `/sessions/{id}/chat` | `{"message":"..."}`，返回本轮 events 数组 |
| POST `/sessions/{id}/stream` | 同上，以 text/event-stream 逐节点发送事件 |

Fake 普通文本回复包含轮数；第二轮发送 `recall` 可获取上一轮用户消息。工具命令是确定的
测试输入格式，不依赖自然语言理解：

```text
read_file {"path":"hello.txt"}
write_note {"name":"first.txt","content":"my note"}
```

`read_file` 只读 `AGENTGUARD_SANDBOX_ROOT/input` 下的 UTF-8 文件（最多 64 KiB），
返回文本规范为 LF，不修改源文件。`write_note` 只在 `notes/{session_id}` 创建新文件
（最多 16 KiB，单一文件名），拒绝覆盖。拒绝绝对路径、遍历、Windows 驱动器/UNC/ADS/
保留设备名和路径中的链接/目录联接。已有硬链接文件不能被覆盖。
沙箱根来自可信服务端配置，不能被请求或模型改写；不要将它指向真实私有数据。
这些是工具自身限制，不是通用工具安全中间件，也不是抗本机恶意进程竞态的 OS 沙箱。

启动另一个 PowerShell，在根目录执行：

```powershell
$demoSession = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/sessions
$demoBody = @{message='write_note {"name":"first.txt","content":"my note"}'} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri ("http://127.0.0.1:8000/sessions/" + $demoSession.session_id + "/chat") -ContentType application/json -Body $demoBody
```

SSE 事件依次包括 session、tool_call、tool_result、message、done；无工具时只有
session/message/done。每轮共享 session_id/trace_id，调用和结果共享 tool_call_id。
JSON 数据中的换行会转义，不能注入新的 SSE frame。session/call 事件在后续节点执行前
发出，不预先缓存整轮；**当前是节点流，不是 DeepSeek 的逐 token 流**。
工具错误以 `tool_result.result={ok:false,error:tool_error}` 返回，随后模型可以完成本轮；
它不意味着 Guard BLOCK。Provider 错误/调用上限发送 error 和 done(ok=false)，不暴露
服务端异常原文。请求体严格限制 1–4096 字符，额外 Provider/密钥/开关字段拒绝且不回显值。

## 真实 DeepSeek：可选手动冒烟

2026-10-20 已在明确授权后完成一次只读工具冒烟：2 次真实请求、904 API 报告 tokens；
详见 `reports/P1-deepseek-real.md`。这不表示真实异常/安全性或 Benchmark 已验证，
下述命令不会被普通阶段检查自动执行。

只有用户明确启用真实实验时才执行。复制 `.env.example` 到忽略的 `.env`，设置：

```dotenv
AGENTGUARD_ENABLE_BASELINE=true
AGENTGUARD_LLM_PROVIDER=deepseek
AGENTGUARD_ENABLE_REAL_API=true
DEEPSEEK_API_KEY=<仅在本地填写真实密钥>
AGENTGUARD_MAX_PROVIDER_CALLS=2
AGENTGUARD_MAX_TOTAL_PROVIDER_CALLS=2
AGENTGUARD_MAX_TOKENS=64
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn agentguard_demo.api:app --host 127.0.0.1 --port 8000 --env-file .env
```

确保当前 shell 没有与 `.env` 冲突的同名变量（已有环境变量优先）。创建会话，发送一次
短文本；检查 session 事件的 provider=deepseek，且收到 message/done(ok=true)。如需
工具冒烟，使用新的进程预算或充足的显式上限，请求在 input 沙箱中的公开样例；一轮工具
调用通常需要两次模型请求。不要将 Fake/MockTransport 的结果记作真实 API 验证。
缺少开关/密钥时启动失败；网络错误/限流/格式错误不自动重试，不记录请求正文/密钥。

固定端点 `https://api.deepseek.com/chat/completions`、模型 `deepseek-chat`、temperature=0，
单次超时 15 秒；不接受来自请求的任意 base_url/model。默认每会话最多 8 次、每进程最多
16 次模型尝试，每响应最多 256 tokens；失败尝试也计数，每轮最多执行 4 次工具调用。
这些上限包括 Fake；进程重启会重置计数。token 上限不限制输入 tokens，不是账户账单上限；
正式实验仍需用户控制总预算。显式禁用 LangSmith tracing，默认 HTTP 客户端不读取代理环境。

## 已知边界

执行会话仅在单进程内存中，重启丢失；基线没有持久历史或 Guard。P7 保护模式另有 SQLite
安全展示历史，重启后旧会话只读；没有身份认证、自动 SSE 重发或生产部署能力。
仅用于本地单用户、无私有数据的实验。工具副作用不能回滚，执行后模型
失败仍可能留下新笔记；中断/重试与恶意本机目录替换的完整加固留待后续阶段。
输入文件和结果未经过 Gate 2；提示注入可以影响此无 Guard 基线。

