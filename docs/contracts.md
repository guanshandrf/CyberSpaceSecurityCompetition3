# 统一事件与决策契约草案（P0）

状态：字段设计草案，尚无 Python 模型、Protocol/ABC 或运行时验证；实现与序列化测试属 P2。
P1 的 HTTP/SSE 使用演示包私有的 session/tool_call/tool_result/message/error/done 传输格式，
含 session_id、每轮 trace_id 和工具 tool_call_id；它们不是 SDK SecurityEvent，
不带 Guard 决策，不构成 P2 契约实现。接口详情见 `apps/api/README.md`。
暂定 schema_version 为 `1.0`，正式支持版本、长度上限与兼容策略由 P2 固化。
所有事件必须可 JSON 序列化，ID 不包含秘密；timestamp 为带时区 UTC 时间。

## 公共字段与三种事件

| 类型 | 必需字段草案 | 语义 |
| --- | --- | --- |
| SecurityEvent 公共字段 | schema_version, event_id, event_type, timestamp, trace_id, session_id | 注册/调用/结果共用 envelope；类型为固定判别值 |
| ToolRegistrationEvent | tool_id, name, source, description, parameters_schema, capabilities, permissions, metadata_digest | 稳定 ID、来源、JSON Schema、能力/权限声明；另带 version 或可验证摘要 |
| ToolCallEvent | tool_id, name, tool_call_id, arguments, source, context_ref | arguments 为结构化 JSON；context_ref 只引用可信后端上下文 |
| ToolResultEvent | tool_id, name, tool_call_id, result_type, content, source, is_error | result_type 区分 text/json/error；保留结果来源 |

工具注册不强制携带 tool_call_id；调用和结果必须关联相同 tool_call_id，并保留 trace_id、
session_id 和工具版本关系。结果需要受控大小限制/截断，另记 truncated、original_size 和
内容证据引用；不能因截断丢失来源或绕过 Gate 2。原始结果与安全结果必须使用不同对象/字段，
禁止清洗失败时回退到原文。

## 上下文、发现与统一决策

| 类型 | 字段草案 | 约束 |
| --- | --- | --- |
| SecurityContext | context_id, user_id, session_id, task_authorization, allowed_resources, permissions, budget, tool_provenance, risk_history | 仅由可信后端构造；不接受 LLM 自报身份/权限 |
| SecurityFinding | code, severity, evidence_ref, detector_id | 只描述检测发现；不直接执行工具或授予权限 |
| SecurityDecision | action, reason_codes, findings, matched_policies, trace_id, tool_call_id, replacement_content | action 为固定枚举；注册决策可无 tool_call_id；替换内容按 Gate 约束 |

`SecurityDecision.action` 统一使用 `ALLOW / BLOCK / REVIEW / SANITIZE`：

- Gate 0：ALLOW 入库；BLOCK 禁止注册/暴露；REVIEW 等待可信审批，不提前暴露。
- Gate 1：仅有效 ALLOW 允许 Executor 执行；BLOCK/REVIEW 未批准时真实执行计数为零。
- Gate 2：ALLOW 返回审核后的安全结果；BLOCK 返回安全替代错误，不能返回原始高风险正文；
  SANITIZE 必须携带 replacement_content，且仅把替换内容交给 Agent。
- 某 Gate 收到不适用动作、关键检查异常或无法验证的上下文时默认拒绝，不能隐式 ALLOW。

REVIEW 的批准主体来自后端；决策须绑定工具摘要、调用参数、上下文、期限和本次调用，
重复、并发和重试不得复用陈旧授权。Detector 输出和风险评分不能覆盖硬性权限拒绝。

## 后续接口职责（仅设计）

Detector 输入统一事件与可信上下文，输出 SecurityFinding 列表；Policy 输入事件、上下文和
findings，输出 SecurityDecision。Gate 0 注册检查，`before_tool()` 属 Gate 1，
`after_tool()` 属 Gate 2；Adapter 负责框架事件转换，Executor/Result Handler 负责落实。
P2 再决定同步/异步签名和 Protocol/ABC，不在 P0 创建空放行实现。

## P2 起需要验证

序列化往返、必填字段/未知字段拒绝策略、无效动作/版本、tool_call_id 关联、JSON 可序列化
和内容大小限制、伪造身份不可注入可信上下文。日志只记录脱敏元数据与证据引用，
不保存真实 API Key、私有凭据或无必要的敏感正文。以上目前均为待实现要求。

