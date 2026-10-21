# 纯 Python Agent 接入

SDK 0.9.0 提供 `agentguard.adapters.simple.SimpleAdapter`，不依赖 LangGraph、FastAPI、
模型 Provider 或 Benchmark。其调用链与 LangGraphAdapter 共用 ToolRegistry/Gate0 →
GuardedExecutor/Gate1 → ResultHandler/Gate2，不复制检测或策略规则。P2 schema 保持 1.0。

可运行示例：从仓库根目录执行 `.\.venv\Scripts\python.exe examples/simple_agent.py`。
这是离线确定性模型替代的实际工具与 SQLite 审计演示，不是真实 LLM 或 Benchmark 成绩。
模型循环只向 `invoke(request, trace_id=...)` 传入以下三字段对象：

```python
request = {"name": "echo", "arguments": {"text": "public fixture"}, "tool_call_id": "call.1"}
reply = adapter.invoke(request, trace_id="trace.turn.1")
model_history.append(reply.safe_event.content)
```

构造器所需 bindings、descriptions、context、registration_context、audit 全部来自可信后端。
`tools()` 仅返回当前已批准且未过期工具的 metadata 副本，不暴露 handler。调用者不得同时向
模型绑定原工具。工具的权限、资源、版本摘要与 context_ref 均由后端确定；额外模型字段、
格式错误或未知工具安全拒绝。非法调用记录关联 ID 和通用原因，不记录原始参数。

SafeReply 仅含 safe_event、executed、两个 Gate 动作以及后端审批引用；没有原始结果。
审批引用不是可给模型的输出，禁止将整个回复对象、原事件或 context 序列化给模型。
`executed=true` 只代表工具已经执行；Gate2 仍可能 BLOCK，无法撤销工具副作用。

人工审批必须由后端保留同一事件，不能重建 event_id/timestamp：

```python
event = adapter.call_event(request, trace_id="trace.approval")
pending = adapter.execute(event)
adapter.approve(pending.approval_ref, approver=trusted_admin)
reply = adapter.execute(event)  # 完整事件、参数、上下文及注册代次重新验证
```

没有批准、到期、拒绝、指纹变化、重放或预算耗尽均不能执行。approval_ttl 和
max_pending_approvals 可在构造时配置；会话限额/创建窗口限流复用执行器默认安全配置。

后端通过 `update_context(current_context)` 发布撤权，保持相同用户和会话；不得将客户端
自报 claims 直接传给 from_backend。慢 Detector 不持有上下文锁，执行点仍由 Executor
检查最新权限和修订号。已开始的副作用不能回滚。

长会话在工具到期后需由可信后端显式调用 `refresh_registrations(current_catalog_context)`，
重新经过 Gate0，验证原摘要和版本；续期不重置执行预算、防重放或审批状态。
`revoke(tool_id, registration_context=...)` 后不能通过续期恢复。需更换版本/工具实现时，
由后端建立新的经审查适配器及新会话；不能重建同一会话以绕过预算。

集成成本包括：定义 ToolBinding/严格 Schema、注入经过认证的后端权限、绑定安全工具元数据、
把模型工具请求接到 invoke、仅回送 safe_event、保留一个会话实例、管理注册续期/审计生命周期。
提供审批界面或异步任务调度属于调用方职责。此适配器本身只支持同步工具。

保护范围限于通过此实例执行的工具；任意 Python 代码执行、反射、原始引用、托管工具、
子 Agent、跨进程/重启后的预算和重放，以及主机被攻陷均不在承诺内。
