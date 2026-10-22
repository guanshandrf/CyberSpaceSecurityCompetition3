# P7 本地聊天与安全审计

Vue 3 + Vite + Element Plus 提供会话列表、节点级 SSE、工具状态、错误及逐调用审计。
“显示安全审计”仅切换前端详情，不传给 API，也不能改变后端 Guard、授权或预算。
保护模式仍须由后端明确配置；页面拒绝连接无 Guard 基线。P2 schema 1.0 和 SDK 未改。

## 启动

先按根 README 安装 SDK、演示包、锁定的 Python/npm 依赖。以下命令工作目录均为项目根。

```powershell
$env:AGENTGUARD_ENABLE_BASELINE='false'
$env:AGENTGUARD_ENABLE_PROTECTION='true'
$env:AGENTGUARD_LLM_PROVIDER='fake'
$env:AGENTGUARD_ENABLE_REAL_API='false'
.\.venv\Scripts\python.exe -m uvicorn agentguard_demo.api:app --host 127.0.0.1 --port 8000
```

在另一个终端执行 `npm.cmd --prefix apps/web run dev`，访问 http://127.0.0.1:5173。
Vite 将同源 `/api` 转到本地 8000 端口；preview 同样配置代理。默认无凭据、无真实模型。
Fake 可发送普通文本、`read_file {"path":"hello.txt"}` 或
`write_note {"name":"first.txt","content":"public note"}`。样例文件需先由用户放入
`.cache/demo/input`，不要指向私有目录。工具命令是确定测试语法，不代表自然语言模型能力。

## 演示应用接口

以下新增传输数据属于演示应用，不是 SDK 的 P2 事件协议。

| 接口 | 行为 |
| --- | --- |
| GET `/sessions` | 最近 100 个持久会话摘要，含 active；保护模式限定 |
| POST `/sessions` | 创建新的、后端拥有预算和权限的会话 |
| DELETE `/sessions/{id}` | 删除会话及展示历史；处理中返回 409，独立 SDK 安全审计保留 |
| GET `/sessions/{id}/history?after=0&limit=200` | 按 sequence 分页读取安全展示事件 |
| GET `/sessions/{id}/audit?after=0&limit=200` | 同样分页，只返回审计投影 |
| POST `/sessions/{id}/stream` | 严格接收 message，返回带 id 的持久 SSE 事件 |
| POST `/sessions/{id}/chat` | 相同保护路径和安全历史，以 JSON events 返回 |

after 为非负整数，limit 为 1–200；响应含 events、next_after、active、mode。
前端读取所有分页，不以单页当作完整历史。未知会话 404，非法参数/额外请求字段 422。
基线历史接口明确返回 409；基线旧聊天格式和独立运行能力保留。

保护模式事件包括 session、user、tool_call、tool_result、audit、message、error、done。
sequence 是 SQLite 全局递增游标，不要求同一会话连续；SSE 与查询使用完全相同的事件。
同会话请求串行化，不同会话分别关联。刷新通过历史查询恢复，不自动重新发送上一条 POST。
SSE 为逐节点反馈，不是模型逐 token 输出；中断只提示状态待核实，不宣称工具未执行。

## 审计投影与保护边界

原 SDK SQLiteAudit 继续保存 HMAC 审计。演示层 PresentationAudit 装饰该 sink，把审计的
白名单字段另存 `history.sqlite`；`audit.sqlite` 保留原 SDK 记录。两路径均经过原 PathRule
验证，拒绝链接/硬链接目标。投影写入失败会向原执行通道传播异常，不能默认放行工具。

对外 trace_id/tool_call_id/tool_id 使用持久、随机盐 HMAC 别名，避免模型提供的 ID 携带
敏感文本；同一数据库重启后别名稳定。只暴露既定工具名称、Gate、stage、action、白名单
reason_codes/matched_policies、风险及耗时，不返回参数、审批 Token、原始 findings 或原文。
未知原因/策略归为 policy.custom，未知工具为 invalid.tool。风险取 finding 的最高等级；
无 finding 显示“未评分”，不编造风险评分。耗时采用 SDK sink 提供的 duration_ms；Gate0
当前上游固定报告 0，不代表已经测量出零延迟。

Gate0 注册有独立生命周期 trace，不伪造成每次调用重新注册；卡片引用当时已存在的同工具
注册审查，并明确标为生命周期记录。Gate1 started 只是准入意图；只有 completed/error 才
显示“已执行”，denied/review 显示“未执行”。Gate2 BLOCK 表示结果被阻断，不能声称此前
工具没执行。执行器后置审计故障可能已产生副作用，未确认状态必须查看历史后人工核实。

聊天历史保存有意用于回显的用户/助手文本，统一再经公共 Redactor 处理已知密钥模式及
显式后端配置的 API Key。工具参数事件只保留 REDACTED，结果仅来自 Gate2 安全通道。
脱敏失败以 withheld 内容替代，不回退原文；该规则不能识别所有未知敏感表达或私人信息。
UI 使用 Vue 文本插值，不使用 v-html、Markdown HTML 或自动外链来执行工具内容。

## 重启、访问和限制

SQLite 持久化的是安全展示历史，不是可执行的 LangGraph 状态。执行器的预算、审批、
防重放仍是原单进程状态；进程重启后旧会话只读，聊天 POST 返回 404，必须新建会话。
这避免用历史恢复重新发放旧会话预算。Provider 的进程预算重启仍会重置，不能当账户预算。

仅绑定回环，HTTP Host 限定本地/testserver，非同源 POST 拒绝，不开放 CORS。无身份认证、
多租户隔离、自动保留策略或远程部署能力；拥有本机访问能力的用户可以读取所有演示
会话。SSE 不自动重试工具调用；断连可能继续执行已准入操作。只保护 Adapter 接管工具。
P8/P9后续工程已交付，完整Benchmark仍有缺口，见最终报告；本轮模型选择修复没有发起真实API。

## 验收

`python scripts/check_phase.py P7` 运行 P0–P7 回归、Ruff、依赖检查和 Web 测试/构建。
`apps/web/src/P7.e2e.test.js` 挂载真实 Vue 页面，通过 stdin 桥接实际 FastAPI TestClient，
运行真实 LangGraph、SDK、沙箱文件和 SQLite，再消费真实 SSE 返回 UI；普通网络连接禁用。
该测试是 jsdom/ASGI 最小端到端验证，不等同于浏览器布局、真实 HTTP 分块时序或 DeepSeek。
组件单测的合成事件仅用于展示分支测试，不冒充实际 API/安全执行结果。
旧 P0 组件移为 P0Shell.vue，原挂载/网络拒绝断言保留。P0–P6 正式命令仍只运行其原两项
Web 测试；P7 正式命令包含所有新 Web 测试。非法后续阶段拒绝测试顺延到未授权 P8。

## 页面模型选择（P7/P9交付后修复）

顶部模型按钮显示当前会话使用离线Fake或真实DeepSeek。Fake仅回显/工具演示，不生成真实问答；
已有对话仍固定原模型，选择模型会创建新会话。DeepSeek选项需确认费用，创建会话本身不请求API。
只向页面返回模型允许列表、可用状态和预算上限，不返回Key；不提供浏览器Key输入框。

后端默认关闭模型选择。要开放选择，从根目录启动时显式设置：

```powershell
$env:AGENTGUARD_ENABLE_PROTECTION='true'
$env:AGENTGUARD_ENABLE_BASELINE='false'
$env:AGENTGUARD_ENABLE_MODEL_SELECTION='true'
$env:AGENTGUARD_ENABLE_REAL_API='true'
$env:AGENTGUARD_LLM_PROVIDER='fake'
.\.venv\Scripts\python.exe -m uvicorn agentguard_demo.api:app --env-file .env --host 127.0.0.1 --port 8000
```

.env只由后端明确读取，DEEPSEEK_API_KEY必须安全配置。没有Key或真实开关时DeepSeek显示为
后端未启用，提交该选项会403；不能由请求提交Key、端点、权限或关闭Guard。
GET /models为演示API配置查询；POST /sessions可选JSON仅为后端允许的provider名称。
这是用户明确要求的演示层选择能力，不修改P2公共SDK协议或SDK依赖。

Fake/DeepSeek及新会话共用同一ChatService预算计数，失败/工具续答同样计数，不能切换模型
重置预算；默认进程上限16、每会话8、每次输出256token，仍是本地演示，重启后进程预算重置。
模型选择/费用确认是本机用户操作，不能提供生产身份认证或账户级预算保证。

## 会话删除与详细审核（2026-10-22 交互补充）

左侧每个会话可点击“删除”，二次确认后才发送 DELETE。删除当前会话后打开剩余会话，
列表为空时清空聊天区域；失败时保留原会话。处理中禁用删除，服务端另用会话展示锁
非阻塞校验，忙时返回 409；删除后排队的旧请求不能再执行。跨源 DELETE 同 POST 拒绝。
删除仅移除内存会话和 history.sqlite 的该会话展示行，不重置共享模型调用预算，不删除
audit.sqlite 安全审计或工具创建的文件；不承诺 SQLite 物理介质上的安全擦除。

逐调用展开详情补充 Gate 职责、阶段中文说明、原因与策略的中文解释和原始白名单代码、
记录时间、风险、可用耗时和执行/结果交付含义。Gate0 为关联的生命周期记录，0ms 标注
“未独立测量”；无记录不推定检查通过，不虚构逐子检查的检测结果。Gate2 阻断明确不能撤销
此前副作用。没有工具调用的轮次展示单独说明，普通文本回答不冒充经过工具安全检测。
详情只使用原有脱敏投影，未新增原参数/原结果/findings/凭据暴露，P2 契约和 SDK 不变。

## 详细安全分析报告（2026-10-22）

每个可展开的工具审计日志中增加“详细分析报告”，纯前端基于相同脱敏记录整理，无额外
API 或模型调用。包括执行结论、记录最高风险、风险类别与证据编号、三个 Gate 覆盖状态、
原有原因码对应的中文解释、时间/trace/call 关联、待核实事项及对应处理建议。

报告只归纳观察证据：Gate1 已执行记录优先保留，后续拒绝/防重放不能抹去先前执行；
Gate2 BLOCK/SANITIZE 分别说明阻断原始结果/仅回传替换内容，不能撤销副作用。
Gate1 started 或 Gate2 ALLOW 均不能单独证明工具已执行；执行错误不能被结果 ALLOW
改写为业务成功。未知风险不计作零风险，缺失日志不推定通过。历史未结束/中断时提示
报告可能不完整。工具注册仍单独标为关联生命周期，不冒充当前调用重审。

耗时只显示本次可用审计记录的最小–最大范围与记录数，排除关联的注册耗时，不把可能
重叠的 started/completed 时间累加为总检查开销。没有工具调用的普通文本轮次也可展开
报告，但不生成工具检查成功结论。现有规则命中仅解释为风险发现，不断言攻击意图或
攻击目标已达成；报告不是新增检测器、语义判断或完整 Benchmark 防护证明。
