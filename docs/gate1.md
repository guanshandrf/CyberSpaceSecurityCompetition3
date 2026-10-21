# P3 Gate 1 与受控执行器

当前 SDK 0.3.0。仅实现调用前检查；无 Gate 0、Gate 2、LangGraph Adapter 或 Web 审批入口。
SDK 运行依赖仍只有 Pydantic，Schema/路径/锁/SQLite 使用标准库。

## 配置与公共 API

`agentguard.policies.ToolBinding` 是可信后端预置的不可变配置，包含 tool_id、name、同步
handler、parameters_schema、非空 permissions 和 task_authorizations、可选 resources、
paths 与 requires_review。配置不能来自模型或未认证请求。它只持有本轮受控执行所需的
映射，不做第三方工具注册准入、描述安全分析、版本审批或代码可信证明；这些属于 P5。
metadata_digest 根据配置计算，调用须引用该值；不包含函数代码哈希。执行器工具集合固定，
重建执行器会丢失预算与重放状态，因此业务不能让请求创建或选择执行器。

`PathRule(parameter, resource_id, root, must_exist=True)` 将一个必需的字符串参数绑定到
后端配置的现有、规范化目录和资源 ID。context.allowed_resources 必须同时包含 tools.resources
以及全部 PathRule.resource_id；这是按配置资源根授权，不提供单文件 ACL 或 URL/数据库查询
语义识别。没有 PathRule 的字符串不被当作文件路径；工具作者必须绑定所有路径参数。
模型只能提供相对文件名，不能选择 root。执行器将已验证路径转换为绝对路径交给 handler。

`agentguard.policies.PolicyEngine(blocked_tools=..., review_tools=...)` 可配置工具拒绝/审批。
默认策略拒绝任何 detector finding；无发现时允许通过硬检查的调用。配置拒绝优先于审批，
ToolBinding.requires_review 不能被自定义 ALLOW 覆盖。可替换的 Policy/Detector 遵守 P2
Protocol；插件属于可信 Python 代码，输出会重验，异常/非法输出会阻断。

`agentguard.gates.Gate1(tools, policy=None, detectors=())` 提供 before_tool(event, context)
以及 Protocol 的 evaluate(event, context)。检查可信上下文及关联、工具 ID/名称/摘要、任务、
权限、资源、Schema、路径和上下文预算；随后调用 detectors/policy，生成 SecurityDecision。
有效调用缺失上下文返回 BLOCK；无法形成有效调用事件时抛通用 ValueError，不回显 payload。
before_tool 不执行工具、不消费预算、不签发可复用授权；完整预算、审批、重放只能由执行器落实。

`agentguard.executor.GuardedExecutor(tools, audit=..., policy=None, detectors=...,
approval_ttl=300)` 提供 before_tool、execute(event, context) 和后端专用 approve。
P3 安全加固新增容量/创建限流配置、cleanup_expired_approvals 和 update_context，详见下文。
execute 不接收外部 Decision；即使先取得 ALLOW，执行时也会重新检查。无效事件返回
ExecutionResult(decision=None, executed=False, error_code="event.invalid")；其他拒绝输出
关联的 BLOCK。检测器和策略在执行器锁外运行；完成后重新检查权限/路径与调用状态。
每会话锁仅串行化最终检查和审计，全局锁仅操作共享计数/索引，不调用插件、文件系统或
审计。执行意图审计成功后，在全局锁内原子核销预算和两个调用标识，再释放锁执行 handler。
审计 started 表示执行意图，只有 executed/完成记录才能证明执行；意图写入期间撤权或审批
过期仍会阻断。允许不同会话和调用并发运行。工具异常仍消费预算、
禁止旧 ID 重试，返回通用 tool.failed，不返回异常正文。暂不支持 async handler。

ExecutionResult 字段为 decision、executed、value、error_code、approval_ref；repr 隐藏
decision/value/approval_ref。value 是原始工具结果，**尚未通过 Gate 2**，不能声称可安全交给
LLM；序列化这些对象仍可能包含敏感内容，不要直接日志记录。

## Schema 的严格支持范围

每个节点必须是带单一 type 的对象，支持 object/array/string/integer/number/boolean/null。
所有 object 必须显式 additionalProperties=false，可用 properties/required/minProperties/
maxProperties；array 必须有 items，可用 minItems/maxItems；string 支持 minLength/maxLength；
integer/number 支持 minimum/maximum/exclusiveMinimum/exclusiveMaximum；全类型支持 enum，
并接受字符串 title/description 注释。拒绝隐式类型转换、默认值和额外参数；bool 不当作数字，
integer 只接受原生 int。P2 的原生有限 JSON、16 层和 16 KiB 参数/Schema 上限保持。

这不是完整 JSON Schema 实现。$ref、format、pattern、组合 Schema、联合 type、默认值及
其他未支持关键字在绑定配置时直接拒绝，不会静默忽略约束，也不会读取引用或联网取 Schema。
不支持的工具必须先转换成该子集，或在后续授权范围内替换验证器。

## 路径与执行边界

拒绝绝对/盘符/UNC 路径、反斜杠、空段、`.`/`..`、ADS、设备名、控制字符、尾空格/点、
通配符、符号链接/目录联接/reparse point、非普通文件及多链接文件。设备名包含 CONIN$、
CONOUT$、COM/LPT 的 1–9 与 Unicode 上标 ¹/²/³，检查忽略大小写、扩展名及设备主名末尾
空格；同一词法规则在所有平台启用，在任何文件系统检查前拒绝。must_exist=False
仅允许现有父目录内的新叶文件；写工具仍需独占创建等自身保护。执行前再次检查文件路径。
所有安全测试使用仓库内临时 fixtures，包括真实硬链接与目录联接；不读取真实敏感文件。

这是应用内授权与静态路径检查，不能原子控制任意 handler 的文件打开方式，不能防止本地
恶意进程在检查与 open 之间替换文件，也不能阻止受信 handler 忽略参数访问其他资源。
资源根及其祖先应由后端/OS 保护；生产工具还需安全句柄、OS 沙箱等。Gate 2 无法撤销副作用。

## 预算、重放和审批

同一后端应共享一个长生命周期执行器，预算以 session_id 核销并绑定首次 user_id。预算上限
取已见可信上限的最小值，已用数量取当前账本与可信 calls_used 的最大值；更换 context_id
或扩大后续 max_calls 不能清零或放宽原账本。每次实际开始执行（含异常）消费 1 次，
BLOCK/待审批不消费。session_id 是可信后端生成，不能由模型无限创建会话绕过总量限制。
此预算只计算工具次数，不计算 API 费用或账户限额。

已执行的 (session_id, tool_call_id) 与 (session_id, event_id) 都不可再次使用；并发重试
最多一次执行，工具异常后若业务明确要再执行，需新的 ID 和剩余预算。

REVIEW 输出不可预测的 approval_ref，记录完整事件（含参数、摘要、trace、ID、时间）和
完整可信上下文的指纹、期限及审批状态。重复待审批调用返回同一引用，不执行工具。
可信后端认证审批者后才可调用：

```python
executor.approve(result.approval_ref, approver=backend_approver, approved=True)
# approved=False 为拒绝；approve 本身从不调用工具。
result = executor.execute(original_call, original_context)
```

审批者必须是 from_backend 构造、有 guard.approve 权限且属于相同 session 的上下文。
应用可施加更严的职责分离；SDK 不提供登录、签名或独立的人审服务，不能把 approve 暴露为
模型工具。批准后执行仍重新检查当前策略、权限、路径和预算；参数/上下文变化、过期、拒绝、
已用审批不能复用。当前过期引用不能续签；建议新业务尝试使用新调用 ID 并重新审核。
过期记录回收后不会保留无限量的审批墓碑；如果重新提交相同未执行 ID 且当前策略仍要求
REVIEW，只会创建新的未批准引用，旧 Token 始终不能批准或授权新记录。已执行 ID 的防重放
账本保持，不随审批回收删除。

### 审批资源限制与过期回收（P3 安全加固）

构造器新增 max_pending_approvals=1024（全局存活记录）、max_pending_per_session=None
（默认 min(64, 全局上限)）、max_approval_creations=256 和 approval_window=60 秒。
创建频率为执行器全局滑动窗口；记录数/频率参数由可信后端配置，未知或非法值拒绝。
等待审批、批准未消费、拒绝及审批写审计中的记录都计入容量，避免绕开容量统计。
重复查询同一未过期调用不新建记录、不额外消耗创建限额；REVIEW 仍不消耗工具执行预算。
达到全局/会话容量返回 BLOCK approval.capacity；达到创建限额返回 BLOCK
approval.rate_limited，均不执行原工具。

审批按固定 TTL 的插入顺序存入 OrderedDict，另建 Token→调用键字典；查询直接索引，
不遍历 values。execute/approve 每次入口回收过期记录，显式
cleanup_expired_approvals() 可供后端空闲清理，返回移除数；无后台线程。
回收同时删除 Token 索引并递减会话计数；消费审批也立即释放两个索引和容量。
清理 k 条过期记录为 O(k)，上界受配置容量控制；无过期记录及 Token 查询为 O(1)。
滑动窗口时间队列只记录成功创建，长度受创建上限控制。空闲时即使未调用清理，内存也
不超过容量上限；后台服务可定期调用清理钩子以提前释放到期记录。

### 检测期间的可信后端撤权

SecurityContext 在 P2 已不可变；SDK 无法自动得知外部权限数据库的变化。可信后端撤权时
须调用 executor.update_context(new_backend_context)，不能仅替换调用方的局部变量。
入口验证 from_backend 来源和同会话用户，发布当前会话上下文并递增内部修订号；P2 事件
字段和 Detector/Policy/Gate Protocol 不变。旧调用传入的上下文不能覆盖已发布的当前权限。

检测完成后执行器读取最新上下文，重做 Gate1.prepare，检查硬权限、资源、任务、预算、
参数/路径和审批绑定；上下文修订变化即使未触发具体硬拒绝也返回 BLOCK context.changed，
防止把旧分析用于新权限。最终原子核销前再次检查修订号、审批期限/状态、预算和重放 ID。
撤权先于核销则阻断；核销在先的已开始调用无法撤销副作用，后端必须考虑此线性化边界。

锁和账本仅在单执行器/单进程内有效，重启清零，没有多 worker、崩溃恢复、分布式核销或
副作用事务。审批已有限额与回收，但会话/已执行 ID 账本仍未持久化或做生命周期清理；
可信后端须限制会话创建和服务线程数量，长期服务需后续工程加固。不得据此宣称生产级
exactly-once。P3 验证线程并发和重试；跨进程/故障恢复属于未验证范围。

## 最小审计

`agentguard.audit.SQLiteAudit(path)` 每次写入独立连接、提交后关闭。执行前审计写入失败
默认阻断；执行完成后的审计故障返回 executed=True、audit.failed_after_execution，不能
声称副作用已撤销。自定义 audit.append sink 是受信配置，必须真实持久化，不应配置空实现。

审计仅存 UTC 时间、gate、动作、阶段、白名单原因码、耗时和 HMAC 后的 event/trace/session/
tool/tool_call 标识；未知自定义原因码变为 policy.custom。不存参数、根路径、内容、用户、
权限、审批 token、finding 原文或异常。HMAC salt 每个 sink 实例随机生成；同实例可关联，
重启不保证历史关联。records() 供本地查看，尚无 UI/SSE 查询集成、保留周期或访问控制。

## 验证入口

```powershell
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.venv\Scripts\python.exe scripts/check_phase.py P3
```

P3 运行 P0–P3 Python 回归及现有前端测试/构建；不调用真实 API 或 Benchmark。
