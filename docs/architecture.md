# AgentGuard 架构（P0 设计基线）

状态：SDK 0.6.0 已实现 Gate 0/1/2、ToolRegistry、受控执行、结果处理和脱敏审计；
P6 LangGraph Adapter 接入受保护演示，独立基线保留。P1 真实 DeepSeek 冒烟见历史补充报告。
P6 安全加固补充 Gate0 重审续期、非法调用审计/消息恢复和中英文组合意图规则，
未变更 P2 协议或总体分层；验收见 `reports/P6-security-fix-acceptance.md`。
P3 公共 API、支持的 Schema 子集、进程/路径限制见 `docs/gate1.md`。

## P2 当前 SDK

`agentguard.contracts` 提供 P2 三类事件、后端上下文、发现/决策模型、解析与
关联检查、Detector/Policy/Gate Protocol，仅依赖 Pydantic 和标准库。
契约层不创建 Gate、Policy Engine 或 Executor；执行层和可选 Adapter 分别实现闭环。Mock Adapter
仅展示数据对照，不执行工具；普通测试始终离线。详情见 `docs/contracts.md`。

## P1 当前可运行路径

`FastAPI → ChatService（内存会话）→ LangGraph StateGraph → LangChain BaseChatModel`
（默认 Fake，可选自定义 DeepSeek HTTP Provider）`→ 工具自身沙箱 → 模型回复`。
API 和演示依赖在 `apps/api` 独立包/requirements-demo.lock 中声明；基线不 import SDK。
保护配置惰性加载公共 SDK Adapter，调用链为 Adapter → Gate1/Executor → Gate2 → 安全消息。
注册在会话初始化时走 Gate0，仅批准元数据/包装进入模型工具集合。无 Guard 基线默认关闭，
仅显式启用时建立会话服务；真实 API 另需开关和密钥，具备基础调用/token 上限。
P7 在演示应用层装饰审计 sink，另存 SQLite 安全展示历史；SSE 逐节点发送聊天和审计投影。
Vue 3/Element Plus 提供聊天和逐调用卡片，审计显示开关不影响防护。执行状态仍为内存，
重启后的历史只读，不重建旧预算/防重放；不是逐 token 输出。见 `docs/web-chat.md`。

## 分层与技术选型

```mermaid
flowchart TD
    UI[Vue 3 + Vite + Element Plus] -->|HTTP / SSE| API[FastAPI]
    API --> Agent[LangGraph + LangChain / DeepSeek Provider]
    Agent --> Adapter[LangGraph Adapter]
    Adapter --> Events[注册 / 调用 / 结果统一事件]
    Events --> G0[Gate 0 注册准入]
    Events --> G1[Gate 1 执行前检查]
    Events --> G2[Gate 2 结果检查]
    G0 --> Policy[Detector Plugins + Policy Engine]
    G1 --> Policy
    G2 --> Policy
    Policy --> Decision[统一 SecurityDecision]
    Decision --> Executor[Guarded Executor / Result Handler]
    Context[可信后端 SecurityContext] --> Policy
    Executor --> Tools[已接管的工具]
    Executor --> Audit[脱敏 Audit / Trace]
    Audit --> SQLite[(SQLite)]
```

这是逻辑依赖图，不表示每次调用都经过 Gate 0。真实生命周期约定如下：

1. Adapter 标准化工具注册/更新，Gate 0 判定后才进入受控工具集合。
2. 每次调用先生成 ToolCallEvent，Gate 1 根据可信上下文、Schema、权限、预算和审批判定。
3. Guarded Executor 仅在本次有效 ALLOW 下执行；BLOCK、未批准 REVIEW 和关键检查异常
   均不执行真实工具。审批完成后须重新验证调用、预算和工具版本，不能复用过期决策。
4. 工具正常或异常输出都生成 ToolResultEvent；Gate 2 处理后，Adapter 才返回安全结果给 LLM。
   BLOCK 不返回原始正文，SANITIZE 必须明确提供替换内容。
5. 审计关联 trace_id / tool_call_id；默认保存脱敏证据引用，避免保存不必要敏感原文。

Gate 2 无法撤销工具已经产生的副作用。保护范围仅为经过 Adapter 和 Guarded Executor
实际接管的调用路径；框架内置/托管或持有原始工具引用的绕过路径不在声明范围。

## 依赖方向

- SDK：Python 3.11+、Pydantic v2；不依赖 API、Web、演示 Agent 或 Benchmark。
- `contracts/core/gates/detectors/policies/executor/audit` 只依赖标准库、SDK 或其必要通用依赖。
- `adapters.langgraph` 使用 langgraph 可选 extra；父包不急切导入框架，Core 不反向导入。
- 演示 Agent 通过公共 SDK 契约/Adapter 接入，不读取 Guard 内部实现。保留默认关闭、
  隔离运行的无 Guard 基线用于受控实验。
- API 使用 FastAPI、SSE 和 SQLite；Web 审计显示开关只控制展示，不影响后端 Guard。
- Benchmark 位于独立目录，其依赖、下载数据和运行环境不污染 SDK 安装。

## 职责与信任

Detector 只报告证据；Policy Engine 决定动作；Executor/Result Handler 强制落实。
可信身份、任务授权、资源范围与预算来自后端，模型输出不能提升权限。风险低分不能覆盖
硬性权限拒绝。关键上下文缺失、策略异常、未注册工具默认拒绝。
工具描述和结果始终是低信任数据，即使通过检测也不升级成系统指令。

## 阶段边界

P1 基线与 Provider；P2 Pydantic 契约与接口；P3 Gate 1/Executor；P4 Gate 2；
P5 Gate 0；P6 LangGraph 闭环；P7 UI/审计；P8 四项评测；P9 异构接入和工程加固。
P0–P7 已实现，core 仍预留；检测器、注册表、执行器和可选 Adapter 具备独立模块。
ToolBinding 是可信执行配置，ToolRegistry 实现注册准入，LangGraphAdapter 组装三 Gate 闭环。
接入方式、生命周期、关联和覆盖限制见 `docs/langgraph.md`。P8–P9 尚未实施。
SDK 默认依赖元数据、源文件静态导入和安装包隔离导入由 P0 测试覆盖；未来动态导入、
第三方插件与实际执行安全须在相应阶段扩展检查，不能用 P0 检查替代。

