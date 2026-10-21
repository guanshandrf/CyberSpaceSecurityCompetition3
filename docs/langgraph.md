# P6：LangGraph 受保护接入

SDK 0.6.0 的可选 `agentguard.adapters.langgraph` 提供 `LangGraphAdapter` 和
`protect(bindings, ...)`。后者构建受保护工具门面，供已有 StateGraph 的模型绑定和工具节点使用，
不重写 Agent 的任务循环。默认 SDK 安装、导入和核心测试不需要框架；只有显式导入本模块时
需要 LangChain Core/LangGraph 可选依赖。离线依赖使用仓库 requirements-demo.lock 的精确版本。

## 后端接入方式

```python
from agentguard.adapters.langgraph import protect

# bindings: 可信后端创建的 ToolBinding 集合，不接受模型上传的 Python callable。
# context: 当前用户的可信执行权限；catalog_context: 注册管理员，具有 tool.register
# 和所有声明权限。二者是同一 session 的 SecurityContext.from_backend 实例。
adapter = protect(
    bindings,
    descriptions=descriptions,  # name -> 说明；注册时经 Gate0 检查
    context=context,
    registration_context=catalog_context,
    audit=audit,               # 例如 SQLiteAudit，必须成功记录才能执行
)

# 每轮由后端产生 trace_id；同一会话必须复用 adapter，不能逐轮重建以重置预算。
adapter.refresh_registrations(current_catalog_context)  # 最新后端权限；过期项重新经过 Gate0
bound_model = provider.bind_tools(adapter.tools(trace_id=trace_id))
graph.add_node("model", model_node)  # model_node 使用上面的 bound_model
graph.add_node("tools", adapter.tool_node(trace_id=trace_id))
# 保留原 START -> model -> conditional(tools/END) -> model 任务循环。
```

`adapter.tools()` 只返回当前 Gate0 已批准且未过期的工具包装；包装保存元数据和受控回调，
没有可供 Agent 另行调用的原始 func/handler。必须替换原工具绑定和原 ToolNode，不能将
两套路径同时放入受保护图。`invoke(call, trace_id=...)` 是严格后端入口，接受
`{name,args,id,type?}`；禁止额外身份/权限/摘要字段。非法 envelope 先记录 BLOCK，再抛通用
ValueError。模型路径使用 `dispatch` 或 `dispatch_many`，后者批量预检 ID；包装和 tool_node
也使用此恢复入口。存在可关联 ID 时返回固定错误 ToolMessage，保持原始 ID；错误结果仍经
Gate2，不执行工具。未知工具、非法参数等有效 envelope 经 Gate1 拒绝。

缺失/重复/不可编码/超长（超过 4096 字符）的 ID 无法安全配对，整批执行前拒绝。
tool_node 同时处理 tool_calls 和 invalid_tool_calls。自定义模型节点可在保存消息前调用
`validate_batch_ids`；循环条件应同时检查两类调用。演示已接入该预检，失败或中断轮次
移除本轮未完成消息，后续轮次可恢复；Executor 的预算与防重放状态不回滚，已产生副作用
也无法回滚。不要把这当成事务或自动重试保证。

SQLiteAudit 用 event.invalid 记录拒绝，原始 ID（即使不符合 P2 Identifier）只保存 HMAC；
内部拒绝 envelope 使用安全替代 ID，不修改 P2 协议，也不能被送去真实执行。参数不进入审计。
自定义 audit sink 可实现 append_invalid_call(decision, tool_call_id=...) 保持原始 ID 的脱敏
关联；仅 append 的 sink 收到合法、确定性映射的 ID。审计故障时默认中止，不回显故障正文。

`refresh_registrations(current_catalog_context)` 是可信后端续期入口。只续期已过期、原先
获准的工具，完整重走 Gate0，并校验同一会话、身份/声明权限、版本和配置摘要；不接收新
handler 或模型提供的元数据。`revoke(tool_id, registration_context=...)` 撤销后不能被续期
复活；续期分析期间撤销也优先。未过期项不重复审查，续期不重建执行器；失败/REVIEW
保持拒绝，后续需要可信后端介入。工具更新仍须原注册接口完整审查，不能用续期偷换版本。

包装支持 invoke/ainvoke/run，框架 ToolCall 传入时保持原始 ID；纯参数字典直接调用时生成
新的 ID。异步入口在线程中执行同步 Executor，不把协程 handler 自动变成受保护工具。
RunnableConfig 不提供权限，包装忽略其中的授权声明。后端可通过
`adapter.update_context(new_context)` 发布撤权；短锁只保护上下文快照，检测器和 handler
不在该锁内运行。执行器会在执行点重验最新权限、预算和调用状态。

## 三种事件与模型边界

1. 初始化时注册生成 ToolRegistrationEvent，经 Gate0，元数据摘要来自可信注册表。
2. 每次模型调用生成新的 ToolCallEvent。trace_id 来自本轮后端，tool_call_id 保留模型 ID，
   session/context_ref、tool_id、摘要来自后端。同一个会话的重复调用 ID 不能再次执行。
3. GuardedExecutor 严格注册模式完成 Gate1/最终核销；ResultHandler 将正常、异常、
   未执行及非法输出统一规范化成结果事件，经 Gate2 后生成安全 ToolMessage。

返回消息的 content 只序列化 safe_event.content；additional_kwargs.agentguard 携带安全
来源和 trace。BLOCK 是固定安全错误，SANITIZE 只有替换内容，raw_event 不离开后端。
ToolMessage 与系统消息权限不同，内容仍为低信任数据；演示系统提示明确禁止遵循结果指令。

`adapter.registrations` 仅供可信后端检查注册决策，可能包含审批引用，不应传给模型/浏览器。
审计 SQLiteAudit.records() 可观察 gate0/gate1/gate2，ID 使用同一 sink 的 HMAC 关联，
不保存参数、正文或异常。Gate0 是注册生命周期 trace，不是每轮执行；可按 session/tool
关联注册与调用，Gate1/2 使用完全相同的本轮 trace/tool_call_id。P6 不增加审计 API 或 Web UI。

## 演示运行

先按根 README 安装 SDK、演示依赖和 apps/api。后端选择一个模式，二者均默认关闭：

```powershell
$env:AGENTGUARD_ENABLE_BASELINE='false'
$env:AGENTGUARD_ENABLE_PROTECTION='true'
$env:AGENTGUARD_LLM_PROVIDER='fake'
$env:AGENTGUARD_ENABLE_REAL_API='false'
.\.venv\Scripts\python.exe -m uvicorn agentguard_demo.api:app --host 127.0.0.1 --port 8000
```

`/sessions` 的 mode=protected，`/health` 的 guard=enabled。Fake 命令和 API/SSE 的业务顺序
保持 P1；保护模式 tool_call.arguments 仅输出 [REDACTED]，tool_result 仅输出安全内容。
客户端不能切换模式或提交权限；基线在 SDK 被拒绝导入的隔离进程中仍能真实写入测试笔记。

演示为本地单用户实验：固定 task.demo、input/会话 notes 资源、file.read/note.write 权限，
并非认证/多租户系统。可由可信 Python 配置 DemoSettings.guard_permissions 限制权限；
max_tool_calls 默认 8，跨轮共享，失败工具执行也消耗预算。Provider 另有 P1 调用/token 上限。
目录仍使用原 SandboxTools：PathRule 先验证并规范绝对路径，后端包装转回相对路径，
工具自身再做校验与独占创建；不削弱其沙箱。审计文件也拒绝链接/硬链接目标。

## 保护范围与限制

- 仅保护通过该 Adapter/Executor 的同步 ToolBinding。框架内置工具、托管工具、子 Agent、
  外部 ToolNode 或保存了原始工具引用的其他路径不在范围内。
- 包装不是恶意 Python 代码沙箱；任意反射、修改进程对象或直接调用受信后端代码不受隔离。
- 注册默认 300 秒 TTL，到期先拒绝；演示由后端在下一轮续期并重审，本门面没有审批 UI。
  REVIEW 不自动批准。P3/P5 原有后端审批能力仍由其公共执行器/注册表提供。
- 内存预算/重放状态为单实例单进程，不能通过重建 adapter 延续；不提供分布式或重启保证。
- Gate2 无法撤销副作用，规则有误报/漏报；原始用户/模型输入也不属于工具结果脱敏范围。
- 本阶段只验证 Windows/Python 3.13.9、真实 LangGraph + 离线 Fake；真实 DeepSeek 保护
  效果、其他平台和所有 Benchmark 均未验证。历史 P1 API 冒烟不能替代 P6 安全验证。
