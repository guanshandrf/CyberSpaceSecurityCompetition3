# 统一事件与安全决策契约（P2，schema 1.0）

状态：P2 已实现 `agentguard.contracts` 中的 Pydantic v2 模型、解析/关联检查和同步 Protocol。
当前 SDK 版本为 0.6.0；P2 wire 契约保持不变，P3 Gate/策略/执行器见 `docs/gate1.md`。
P1 的 HTTP/SSE 使用演示包私有的 session/tool_call/tool_result/message/error/done 传输格式，
含 session_id、每轮 trace_id 和工具 tool_call_id；它们不是 SDK SecurityEvent，
它们是传输格式；受保护模式内部由 P6 Adapter 转换为 SDK 事件，只返回 Gate2 安全结果。
接入与关联见 `docs/langgraph.md`，HTTP 接口见 `apps/api/README.md`。
P7 保护模式增加私有 user/audit 展示事件及 sequence，并对外提供稳定 HMAC 标识别名；
历史/审计查询及 SSE 传输详见 `docs/web-chat.md`，P2 公共事件源码与 schema 未修改。
schema_version 固定为必填的 `1.0`，拒绝其他版本，不进行隐式迁移。未知字段一律拒绝，
禁止字符串/数字/布尔值之间的自动转换。所有事件可 JSON 往返；timestamp 必须带时区，
接收 ISO 8601 时间并规范到 UTC。ID 为 1–128 字符、以字母/数字开头，仅允许字母、数字、
`_ . : -`；source 是 1–256 字符无空白的来源标识或 URI，不代表其来源已被认证。

## 公共字段与三种事件

| 类型 | 必需字段草案 | 语义 |
| --- | --- | --- |
| SecurityEvent 公共字段 | schema_version, event_id, event_type, timestamp, trace_id, session_id | 注册/调用/结果共用 envelope；类型为固定判别值 |
| ToolRegistrationEvent | tool_id, name, source, description, parameters_schema, capabilities, permissions, metadata_digest | 稳定 ID、来源、JSON Schema、能力/权限声明；另带 version 或可验证摘要 |
| ToolCallEvent | tool_id, name, metadata_digest, tool_call_id, arguments, source, context_ref | arguments 为结构化 JSON；context_ref 只引用可信后端上下文 |
| ToolResultEvent | tool_id, name, metadata_digest, tool_call_id, result_type, content, source, is_error | result_type 区分 text/json/error；保留结果来源 |

工具注册禁止携带 tool_call_id；调用和结果必须关联相同 tool_call_id、tool_id、name、
metadata_digest、trace_id、session_id，且事件本身的 event_id 不同。
metadata_digest 必须是 64 位小写十六进制；version 可选。P2 只验证格式/引用一致性，
不证明元数据可信，也不自行计算工具元数据摘要，注册准入属于 P5。
参数 Schema 顶层必须声明 object，若有 properties 必须是对象；完整 Schema 语义及
调用参数是否匹配 Schema 由 P3 严格子集校验，P2 契约模型自身不做权限或执行判定。

事件必须通过 `parse_event(raw)` 解析，raw 可为 JSON str/bytes、Python 字典或现有事件。
根据 event_type 只接受 ToolRegistrationEvent / ToolCallEvent / ToolResultEvent 三类，
不能直接构造基类 SecurityEvent 替代完整事件。也可调用具体类型的 model_validate_json。

参数和 Schema JSON 编码上限各 16 KiB，结果和替换内容各 64 KiB，JSON 嵌套最多 16 层，
parse_event 的字符串/bytes 输入总上限 256 KiB。只接受原生有限 JSON：字符串、布尔、
整数、有限浮点、null、list、字符串键 dict；拒绝 bytes、tuple、集合、datetime、NaN/Inf、
循环引用等。description 为 1–8192 字符。入参 JSON 做副本，避免调用者持有的原容器串改。

结果 text 必须是字符串，error 与 is_error=true 必须一致；json 可包含任意合法 JSON。
P2 不自动截断：超限会拒绝。显式 truncated=true 时，必须有 evidence_ref 和比保留内容
更大的 original_size；非截断 original_size 若提供必须等于保留内容的规范 JSON UTF-8
编码字节数（包括 JSON 引号，使用无额外空白的 separators）。不能借截断丢失溯源。
Gate2 原始/安全结果处理和禁止回退原文由 P4 ResultHandler 实现，见 `docs/gate2.md`。

## 上下文、发现与统一决策

| 类型 | 字段草案 | 约束 |
| --- | --- | --- |
| SecurityContext | schema_version, context_id, user_id, session_id, task_authorization, allowed_resources, permissions, budget；可选 tool_provenance/risk_history | 仅由可信后端构造；不接受 LLM 自报身份/权限 |
| SecurityFinding | code, severity, evidence_ref, detector_id | 只描述检测发现；不直接执行工具或授予权限 |
| SecurityDecision | schema_version, gate, event_id, trace_id, session_id, tool_id, action, reason_codes；调用/结果必需 tool_call_id；可选 findings/matched_policies/replacement_content | 没有默认 ALLOW，reason_codes 不得为空；动作和替换内容按 Gate 约束 |

SecurityFinding 的 severity 为 info/low/medium/high/critical，evidence_ref 只保留引用，
不接受额外 raw_content 字段。字段冻结，身份、权限、资源列表规范为 tuple；CallBudget 的
max_calls 为 1–1,000,000，calls_used 为非负整数，可表示预算已经超限，但 P2 不消耗预算。

### 可信后端上下文

```python
from agentguard.contracts import SecurityContext

context = SecurityContext.from_backend(
    schema_version="1.0", context_id="context.1", user_id="backend.user",
    session_id="session.1", task_authorization="task.read",
    allowed_resources=["fixture.sample"], permissions=["fixture.read"],
    budget={"max_calls": 2, "calls_used": 0},
)
```

此入口只能由可信后端调用，**不能把模型输出或客户端请求直接转交给 from_backend**。
直接构造、model_validate/model_validate_json 及声称 trusted=true/backend=true 的 JSON
都不能获得内部来源标记。上下文的身份/权限/预算不可变，model_copy(update=...) 也禁止；
model_construct 绕过验证的上下文没有可信来源，关联检查会拒绝它。序列化不包含来源标记；
从受信存储恢复时必须由后端重新验证并显式调用 from_backend。
这是一条进程内应用边界，**不是身份认证、签名或恶意 Python 代码沙箱**；持有任意代码
执行能力的可信进程能调用公开后端入口。后端认证与上下文选择仍是调用方责任。

`SecurityDecision.action` 统一使用 `ALLOW / BLOCK / REVIEW / SANITIZE`：

下述执行效果是后续 Gate/Executor 的职责；P2 只验证数据形状和动作适用 Gate，不执行动作。

- Gate 0：ALLOW 入库；BLOCK 禁止注册/暴露；REVIEW 等待可信审批，不提前暴露。
- Gate 1：仅有效 ALLOW 允许 Executor 执行；BLOCK/REVIEW 未批准时真实执行计数为零。
- Gate 2：ALLOW 返回审核后的安全结果；BLOCK 返回安全替代错误，不能返回原始高风险正文；
  SANITIZE 必须携带 replacement_content，且仅把替换内容交给 Agent。
- 某 Gate 收到不适用动作、关键检查异常或无法验证的上下文时默认拒绝，不能隐式 ALLOW。

当前模型在 Gate 0/1 拒绝 SANITIZE、Gate 2 拒绝 REVIEW；Gate 2 SANITIZE 必须带显式
非 null replacement_content，其他动作不允许携带非 null replacement_content。
Gate 0 的 tool_call_id 必须为空；Gate 1/2 必须提供。BLOCK 的通用安全错误由
结果处理器生成，不通过 replacement_content 传递原始正文。

REVIEW 的批准主体来自后端；决策须绑定工具摘要、调用参数、上下文、期限和本次调用，
重复、并发和重试不得复用陈旧授权。Detector 输出和风险评分不能覆盖硬性权限拒绝。

## 已实现的接口与关联校验

同步、runtime_checkable 的结构化 Protocol（没有默认放行实现）：

```text
Detector: detector_id; detect(event: UnifiedEvent, context) -> tuple[SecurityFinding, ...]
Policy:   policy_id; evaluate(event, context, findings) -> SecurityDecision
Gate:     gate_id; evaluate(event, context) -> SecurityDecision
```

runtime_checkable 只能检查对象形状，不验证签名语义或策略正确性。Core 不 import Agent 框架，
before_tool/Executor、after_tool/ResultHandler、Gate0/Registry 和 P6 Adapter 均在独立层实现。

`validate_correlation(event, context=..., call=..., decision=...)`：必须提供后端构造的 context，
校验 session/context_ref；结果必须提供原调用并核对上述关联字段；可选 decision 必须绑定
当前 event_id/trace/session/tool/call，并使用对应 Gate。关联失败抛出 CorrelationError，
没有任何工具副作用。

字段冻结不等于嵌套 JSON 不可变；使用 parse_event 和关联检查会在序列化之前重新验证
原始字段，避免 NaN→null、bytes→text 等有损转换掩盖非法值。P2 不提供执行授权、重放
防护、参数摘要绑定、审批、预算核销或并发保护；P3 执行器已在执行点落实这些检查，见 gate1 文档。

## 使用与已覆盖测试

序列化往返、必填字段、严格类型、额外字段、动作/版本、tool_call_id/trace/工具摘要关联、
JSON 限制和变更后重验、上下文伪造/复制变更拒绝均有离线测试。
各模型提供 model_json_schema()；联合事件的 schema 可由 TypeAdapter(UnifiedEvent) 获得。
`examples/mock_adapter.py` 展示三类合成事件的归一化、往返和关联，实际工具执行数为零，
不代表真实模型或 Benchmark 实验：

```powershell
.\.venv\Scripts\python.exe examples/mock_adapter.py
.\.venv\Scripts\python.exe scripts/check_phase.py P2
```

内容/参数不进入模型 repr，验证错误字符串隐藏输入；调用方记录结构化错误时仍需使用
`errors(include_input=False)`，不得直接记录原始事件或 model_dump_json。序列化为传输所需
会包含 payload，P2 没有通用密钥检测、脱敏器或审计存储；这些不能由“通过模型验证”推断。

