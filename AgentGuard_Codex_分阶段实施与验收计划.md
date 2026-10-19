# AgentGuard：Codex 分阶段实施与验收计划（V1.0）

> **项目定位**：面向异构 LLM Agent 的可插拔提示注入与工具调用安全防护中间件。  
> **项目组成**：① LangGraph + DeepSeek API 的 Web Agent 演示平台；② 独立 Python AgentGuard SDK；③ 使用四个公开 Benchmark 的评测平台。  
> **核心原则**：安全系统与 Agent 业务逻辑解耦；工具注册、执行前、结果返回分别由 Gate 0/1/2 检查；**所有受保护工具必须通过强制受控执行通道**。  
> **状态**：本文件是待实现的计划与验收标准，**不是已实现功能清单**。

## 0. 给 Codex 的最高优先级执行约束

1. **严格按 P0 → P9 顺序实施，一次只做一个阶段。** 每完成一个阶段必须执行该阶段验收命令，生成验收报告并停止，等待我明确回复“进入下一阶段”。不要自行把后续阶段提前做完。
2. 每阶段先读取 `docs/architecture.md`、`docs/contracts.md`、`docs/threat-model.md` 和本计划；按“计划 → 最小实现 → 测试 → 结果报告”执行。先满足验收要求，再优化代码；不得为了测试通过而降低安全规则或删除失败用例。
3. **所有自动化测试默认离线运行。** 采用 Fake/Stub LLM、隔离的临时工具和固定样例；不能要求真实 DeepSeek API Key，也不能产生实际外发或危险副作用。真实 API、外部 Benchmark 的下载/运行需要明确配置后单独触发。
4. API Key 仅存放在环境变量和本地忽略的 `.env` 中，提供 `.env.example`；不得输出到日志、审计记录、浏览器、Git 或测试快照。危险工具仅使用沙箱模拟，不执行真实泄漏、系统破坏或不受控网络访问。
5. 保持模块边界清晰：`agentguard` SDK 不能 import 演示 Agent、FastAPI、Vue 或 Benchmark；Adapter 可以 import Agent 框架；演示 Agent 不得直接依赖 Guard 内部实现。
6. 有明确失败时**默认阻断（fail closed）**：关键检查异常、上下文缺失或审批未完成时，不得放行受保护的高风险工具。开发/实验中可以有“无 Guard 基线”，但必须显式隔离、默认关闭，禁止在生产配置中无提示绕过。
7. 阶段完成后提交 `reports/Px-acceptance.md`，写明：完成内容、变更文件、运行的精确命令、测试通过/失败/跳过数、人工验证结果、限制和遗留风险、下一阶段建议。**任何未执行的测试不得写作“通过”；遇到缺少依赖、环境或额度必须写明“未验证”。**
8. 每阶段通过后建议创建 Git 提交或标签（例如 `phase-p3-passed`），便于回退；不得自动覆盖既有用户文件，不执行危险清理命令。

## 1. 已确认的范围和选型

- **LLM**：DeepSeek API；不进行模型本地部署。通过 LangChain 的兼容客户端/自定义 Provider 封装配置，运行时按实际支持情况对齐调用方式。
- **Agent**：LangGraph（配合 LangChain 模型/工具封装）；保留一个不依赖 AgentGuard 的基础版本，作为防护前后对照对象。
- **API 服务**：FastAPI；支持多轮会话和流式事件（优先 SSE）。
- **Web**：Vue 3 + Vite + Element Plus，DeepSeek 风格聊天体验；“显示安全审计”只是展示开关，**不是 Guard 启停开关**。
- **SDK**：Python 3.11+、Pydantic v2、pytest、Ruff；SQLite 用于会话和脱敏审计（本地 MVP）。
- **插件与集成**：Adapter + Tool Wrapping + Guarded Executor；Detector Plugins + Policy Engine；对外公开稳定的事件/决策接口。
- **仅使用四个 Benchmark**：AgentDojo、InjecAgent、MCP Security Bench（MSB）、τ³-bench。前三者负责安全评估，τ³-bench 重点评估正常任务可用性。先做兼容性验证，再决定可运行样本规模，不假设仓库即插即用。
- **暂不做**：本地 LLM 训练/部署、分布式微服务、复杂多租户计费、全面支持任意 Agent、生产级恶意代码执行。第二个异构 Agent 的接入用于最终验证可插拔性，工作量可控。

## 2. 目标架构与必须遵守的调用关系

```text
Web Vue Chat / Audit Dashboard
             │  HTTP/SSE
             ▼
         FastAPI
             │
             ▼
    LangGraph + DeepSeek API
             │  注册工具 / 发出 Tool Call
             ▼
       LangGraph Adapter
             │  标准化事件
             ▼
   ┌──────── AgentGuard SDK ───────────────────────┐
   │ Gate 0: 工具注册/更新准入（注册时）               │
   │ Gate 1: 每次工具执行前审查                      │
   │  → Detector(s) → Policy Engine → Decision    │
   │  → Guarded Tool Executor（仅 ALLOW 才执行）    │
   │ Gate 2: 工具结果返回前审查                      │
   │  → Detector(s) → Policy Engine → Decision    │
   │ SecurityContext / Audit / Trace              │
   └───────────────────────────────────────────────┘
             │
             ▼
   Adapter 将审核后的结果交回 Agent
```

**重要说明**：上述是**逻辑结构**，运行时的实际顺序是：注册工具 → Gate 0；每次调用 → Adapter → Gate 1 → Guarded Executor → 工具执行 → Adapter 生成标准结果事件 → Gate 2 → 返回 Agent。Gate 0 不是每轮调用都执行。Gate 2 无法撤销已执行工具的副作用。

### 2.1 统一事件协议（SDK 公共契约，Pydantic）

- `SecurityEvent` 公共字段：`schema_version`、`event_id`、`event_type`、`timestamp`、`trace_id`、`session_id`；相关调用携带 `tool_call_id`。
- `ToolRegistrationEvent`：工具稳定 ID、名称、版本或元数据摘要、来源、描述、参数 JSON Schema、能力/权限声明。
- `ToolCallEvent`：工具 ID/名称、`tool_call_id`、结构化参数、调用来源、可信上下文引用。
- `ToolResultEvent`：工具 ID/名称、`tool_call_id`、结果类型与内容（文本/JSON/错误等）、来源和错误标识；需要允许受控截断/大小限制并保留必要溯源字段。
- `SecurityContext`：由可信后端注入用户身份、会话、任务授权、可访问资源、预算、工具来源/风险历史。**不采信 LLM 自报的权限**。
- `SecurityFinding`：检测器输出 `code`、`severity`、`evidence_ref`、`detector_id` 等，不直接决定是否执行。
- `SecurityDecision`：统一输出 `action`（`ALLOW` / `BLOCK` / `REVIEW` / `SANITIZE`）、`reason_codes`、`findings`、命中策略、可选安全替代结果、`trace_id`/`tool_call_id`。Gate 2 的 `SANITIZE` 必须返回明确的替换内容，不允许返回原始高风险正文。

### 2.2 检测、决策、强制执行的分工

- **Detectors**：输出证据与风险发现，如文本注入、敏感数据、Schema 异常、权限/资源异常。
- **Policy Engine**：结合可信 `SecurityContext` 与发现生成统一决策；**硬性权限约束优先于概率评分**，拒绝规则优先于允许规则。
- **Guarded Executor / Result Handler**：落实决策，管理审批状态、工具生命周期和异常；原始工具不能同时暴露给受保护 Agent。
- **Audit**：记录事件、策略命中、决策和耗时；默认脱敏，不存真实 API 密钥和不必要的原始敏感内容。
- **范围边界**：只能保证被 Adapter/执行器实际接管的工具受到检查。对框架内置、托管或绕过 Adapter 的工具不得宣称“全部覆盖”，需在文档中列出覆盖范围。

## 3. 推荐仓库结构

```text
AgentGuard/
├── pyproject.toml                 # Python 项目/工具配置
├── src/agentguard/
│   ├── contracts/                # 事件、上下文、决策协议
│   ├── core/                     # Guard 协调器
│   ├── gates/                    # gate0 / gate1 / gate2
│   ├── detectors/                # 检测插件
│   ├── policies/                 # 策略引擎与策略加载
│   ├── executor/                 # 强制执行与结果处理
│   ├── adapters/                 # langgraph / simple-agent
│   └── audit/                    # 审计与追踪
├── apps/api/                     # FastAPI + Agent Demo
├── apps/web/                     # Vue 聊天/审计界面
├── benchmarks/                   # 四种 Benchmark 的独立适配/报告
├── configs/                      # 权限/检测/运行配置
├── fixtures/                     # 无害任务、受控攻击样例
├── tests/unit/                   # SDK 单测
├── tests/integration/            # Agent/Adapter/Executor 集成
├── tests/security/               # 关键安全属性/回归
├── tests/e2e/                    # Web/E2E（需要时）
├── docs/                         # 架构、接口、威胁模型、评测协议
├── reports/                      # 阶段验收与评测报告
└── scripts/                      # 可重复验收脚本
```

## 4. 阶段计划与验收门槛（严格顺序）

### P0 — 项目骨架、接口文档与验收基础

**任务**：建立 Python/Vue 工程骨架、依赖锁定、`.env.example`、测试配置、基础 CI 或本地 `make check`；创建架构图、威胁模型、事件字段草案、四个 Benchmark 的预期接入方式清单。提供 `scripts/check_phase.py` 或等价命令，能按阶段运行指定测试并生成结果文件（不要仅检测文件是否存在）。

**产物**：可安装 Python 包骨架、空前端工程、`docs/architecture.md`、`docs/contracts.md`、`docs/threat-model.md`、`docs/evaluation-plan.md`、`reports/P0-acceptance.md`。

**验收**：全新环境按 README 安装；lint + 基础 smoke tests 通过；没有 API Key 也能执行；确认 SDK 没有 import Web 框架/演示 Agent。**未通过不进入 P1。**

### P1 — 无 Guard 的基础 LangGraph Agent + DeepSeek 接口

**任务**：搭建 LangGraph Agent、模型 Provider 配置、多轮对话、工具调用、最小 FastAPI 聊天接口/流式输出。先提供两种可测试工具：`read_file`（只读沙箱）和 `write_note`（仅写测试目录）。DeepSeek API 用 `.env` 按需启用；默认 Fake LLM，支持可预测的 Tool Call。

**产物**：基线 Agent、工具、会话接口、Fake LLM、离线集成测试、可选真实 DeepSeek 手动冒烟步骤。

**验收**：Fake LLM 下：两轮会话成功；至少一次工具调用完成；受限文件读写符合工具自身沙箱约束；API/SSE 收到正确的会话与工具事件。真实 DeepSeek 若无凭据，只标注“未验证”，不得阻塞离线验收。

### P2 — 统一事件协议与安全决策接口

**任务**：实现 Pydantic 的 `SecurityEvent`、三类工具事件、`SecurityContext`、`SecurityFinding`、`SecurityDecision`；设计版本字段、ID 关联、可序列化内容、非法字段验证；搭建 Detector/Policy/Gate 的 Protocol/ABC，禁止 Core 直接 import LangGraph。

**产物**：可单独安装和导入的 `agentguard` SDK 契约层、公共 API 文档、Mock Adapter 对照样例。

**验收**：序列化/反序列化、缺失必填字段、无效动作、版本校验、`tool_call_id` 关联、伪造身份不可进入可信 `SecurityContext` 的测试通过；无 Agent 环境可独立测试。

### P3 — Gate 1 + Guarded Executor：强制调用前审查（最高优先级）

**任务**：实现 `before_tool()`、策略引擎、参数/schema 校验、路径/权限边界、调用预算、审批状态、默认拒绝规则、受控工具执行器；任何被拒绝的工具不得产生副作用。实现基础审计（脱敏）。

**产物**：Gate 1、Guarded Executor、可配置策略、关键安全属性测试。

**验收**：至少验证 ①授权文件读取 ALLOW；②未授权路径 BLOCK、原工具执行计数为 0；③非法 Schema BLOCK；④重复/超预算调用 BLOCK；⑤策略异常/缺失可信上下文时不放行；⑥`REVIEW` 在未批准前无副作用；⑦并发/重试不因复用旧 Decision 绕过校验。测试不触达真实敏感文件。

### P4 — Gate 2：工具返回内容检查

**任务**：实现 `after_tool()`，对标准化工具结果进行来源标记、提示注入检测、角色/用户伪装识别、敏感信息脱敏；支持 `ALLOW/BLOCK/SANITIZE`，保留原始结果和返回 Agent 的安全结果的明确区分。先规则检测 MVP，语义检测可作为可替换插件（不依赖真实 API 通过离线测试）。

**产物**：Gate 2、规则 Detector、Redactor、安全结果处理器、审计记录。

**验收**：受控恶意文档试图改变指令时被处理；正常安全研究文本不应仅因出现关键词全部拦截（提供上下文区分样例）；`BLOCK` 不向模型返回原始内容；`SANITIZE` 只返回替换内容；工具异常返回也通过安全结果处理；审计不泄漏敏感原文。

### P5 — Gate 0：工具注册与更新审查

**任务**：实现工具注册事件检查：工具 ID/来源、名称与说明、参数 Schema、能力/权限声明、元数据摘要；检测可疑描述与越权能力，执行允许/拒绝/人工审核；工具变更必须重新审查，未经注册或过期的工具不得通过 Gate 1。

**产物**：Tool Registry、Gate 0、受控工具集合生成器、注册审计。

**验收**：正常工具可注册；可疑工具描述触发检测或审核；被拒绝工具不可暴露给 Agent；同名冲突/更换版本需重新判定；Gate 1 对未批准工具拒绝执行。明确文档说明：仅凭静态元数据不能保证第三方 Skill 代码安全。

### P6 — LangGraph Adapter 接入与端到端安全闭环

**任务**：将 P1 基线 Agent 的工具绑定改为可开关的受保护工具包装；Adapter 转换注册/调用/返回三类事件；保持原 Agent 任务逻辑不变，将真实工具调用统一导入 Guarded Executor。支持 trace 和 tool_call_id 在多轮、并发工具调用下关联。

**产物**：`LangGraphAdapter`、`protect(agent, ...)` 的可用封装（具体形式以框架扩展机制为准）、演示 Agent baseline/protected 两种配置、端到端集成测试。

**验收**：相同任务中 baseline/protected 都能完成合法工具调用；受保护模式未授权操作零副作用；恶意工具结果由 Gate 2 处理；可同时观察三个 Gate 的事件；对受保护工具不存在绕过原始引用的调用路径；多次调用的 trace 关联正确。把**受保护范围、无法拦截的内置/托管工具**写入文档，不夸大覆盖。

### P7 — Web 聊天界面与逐条安全审计

**任务**：Vue 3 + Element Plus 搭建 DeepSeek 风格聊天页：会话列表、流式消息、工具调用进度、错误状态；顶部“显示安全审计”开关；按消息显示一个或多个工具调用的审核卡片，可展开 Gate 0/1/2、策略命中、风险等级和耗时。后端通过 SSE 发送可脱敏的审计事件并落库。

**产物**：可运行 Web UI、API 审计查询、前端测试和最小 E2E。

**验收**：普通/审计两种显示模式切换正确；隐藏审计**不关闭 Guard**；单条 Agent 回复触发多个工具调用时分别显示 trace；拒绝时 UI 正确显示“未执行”；刷新后能查询历史审计；XSS 和敏感信息展示检查通过；`npm run build` 与前端测试通过。

### P8 — 四项 Benchmark 评测、消融与可复现报告

**任务**：只接入 AgentDojo、InjecAgent、MSB、τ³-bench。先记录每套框架的版本、许可、运行要求和适配成本，完成少量 smoke cases；在可运行子集上再执行对比：baseline（无 Guard，仅受控实验环境）、规则版、完整 AgentGuard、必要的单 Gate 消融。所有实验固定模型名称、参数、任务 ID、攻击输入与重复次数。

**产物**：独立 Benchmark adapters、可复现运行脚本、结构化结果 JSON/CSV、汇总实验报告与失败样例分析。

**验收**：每个被宣称“已接入”的 Benchmark 都能加载案例、执行、读取原始判定与产出报告；统计 ASR、正常任务成功率、误拦截、延迟、Token/API 成本（数据可用时）；模型主动拒绝与 Guard 阻断分别计数；至少完成一轮小规模基线-防护对比。若某套 Benchmark 无法适配，明确写“未接入/部分接入”和技术原因，**不得造假、不得捏造成绩或把 Mock 结果写作真实模型结果**。

### P9 — 异构接入验证、工程加固与交付

**任务**：增加一个与 LangGraph 执行循环不同的轻量 Agent/适配器，复用相同 Security Core；补充异常/并发/重试/过期审批测试、性能压测、文档、演示脚本、部署说明和最终验收清单；避免为了展示“跨框架”而复制 Guard 规则代码。

**产物**：第二 Adapter、完整文档、架构图、威胁模型、演示脚本、最终报告、可安装 SDK、可复现测试命令。

**验收**：两套 Agent 均使用相同 Gate/Policy/Detector 实现；通过非法工具调用、恶意返回、工具版本变更及并发测试；从干净环境可完成安装、离线测试、演示；最终报告清楚列出防护收益、接入成本、性能开销和不覆盖的风险。

## 5. 统一阶段验收方法（Codex 必须落实）

- **公共命令目标**：提供 `make check`（lint + 单测 + 核心集成/安全回归）；`python scripts/check_phase.py P0` 至 `P9` 或等价命令。Windows 用户可提供 Python 脚本替代 Makefile。各阶段脚本必须运行相应测试并返回非零退出码（失败时）。
- **每阶段最小验证**：单元测试 + 该阶段集成/安全测试 + 现有阶段回归。若包含 UI，再执行 `npm run test` 和 `npm run build`。不得使用“检查有几个文件”替代行为测试。
- **检验报告格式**：

```text
阶段编号：P?
目标/完成情况：
新增或变更文件：
执行命令与环境：
自动化测试：通过 ? / 失败 ? / 跳过 ?
手动验证：
安全不变量是否保持：是/否/未验证
无法验证的项目与原因：
已知风险：
结论：PASS / FAIL / PARTIAL
下一步建议：
```

- **PASS 条件**：本阶段约定的必要行为测试全通过，旧阶段回归不退化，未声称未验证的能力已实现。`PARTIAL` 或 `FAIL` 均**停止，不能自动进入下一阶段**。

## 6. 核心安全不变量（每阶段不得破坏）

1. 未注册/未授权工具调用不能被 Guarded Executor 执行。
2. Gate 1 返回 BLOCK 或 REVIEW 未批准时，**真实工具副作用为零**。
3. Gate 2 处理前，未经审核的工具结果不能进入下一轮 LLM 上下文。
4. 工具返回内容为低信任数据，清洗或检测通过**不提升其指令权限**。
5. 可信授权不来自 LLM 生成文本；权限决策不能被风险低分覆盖。
6. 审计信息中的密钥、敏感参数与恶意结果默认脱敏；UI 不直接呈现原始敏感内容。
7. 任何“保护全部工具”的表述必须限定为**实际接管的工具执行路径**。
8. Benchmark 的评测成绩来自可复现执行，不来自预填常量、Mock 冒充或推测。

## 7. 第一条给 Codex 的执行指令（复制使用）

> 请把本文件作为项目的最高优先级实施计划，**本轮只执行 P0**。先检查仓库现状并输出 P0 的文件改动计划，随后建立最小工程骨架、架构/接口/威胁模型文档、离线测试与阶段验收脚本。运行 P0 全部验收命令并将实际结果写入 `reports/P0-acceptance.md`。若未满足验收标准，请修复 P0 的问题，不要提前实施 P1。完成后停下，汇报本阶段产物、测试结果、风险和需要我确认的事项，等待我回复“进入 P1”。

---

**成功标准（一句话）**：同一套独立 AgentGuard SDK 通过 Adapter 接入不同 Agent，对接管的工具提供 Gate 0 注册准入、Gate 1 强制执行前审查和 Gate 2 结果审查，并能在四个指定 Benchmark 的可复现实验范围内量化安全收益与正常任务影响。
