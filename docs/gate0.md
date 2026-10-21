# P5 工具注册和生命周期

ToolRegistry(audit=..., gate=None, ttl=300, max_tools=128) 只接收可信后端 ToolBinding，
register(binding, backend_context, description=..., source="backend.local", version="1",
capabilities=...) 生成 ToolRegistrationEvent，并交给 Gate0。调用方须有 tool.register
且拥有工具声明的权限；允许来源和拒绝能力由后端配置。可疑描述触发 REVIEW；未知来源、
危险能力、权限不足、非法 Schema 或关键异常 BLOCK。静态元数据不能证明第三方代码安全。

元数据摘要同时绑定 ToolBinding 的安全配置摘要、名称、来源、描述、Schema、版本、能力
和权限。相同 ID 更新立即使旧准入失效，重新分析后才可 ALLOW；名称冲突拒绝。返回的
RegistrationResult.event 为分离快照；不会通过可变 Schema 串改内部获准元数据。
注册表和审批 Token 都受 max_tools 约束，不保持无限历史。过期或撤销工具不在 bindings()
中暴露，不能被严格执行器调用；REVIEW 审批仅由有 tool.approve 的同注册会话后端完成。

GuardedExecutor(..., registry=registry) / Gate1(..., registry=registry) 是 P5 严格通道。
未注册、未批准、过期、撤销、摘要/名称不一致均拒绝，实际执行计数为零。执行前持有短时
准入租约，复核注册代次与硬权限，再原子核销调用；审批指纹也绑定注册代次。租约不覆盖
插件分析、审计或工具主体，更新/撤销在最终核销之前生效；已开始的副作用无法撤销。

P3 兼容入口 registry=None 仅接受后端预置绑定，保持旧行为，不宣称 Gate0 防护。
P6 受保护 Adapter 必须配置 registry，不能走该兼容入口。注册表按单实例单进程保存，
重启清零，无持久化/分布式保证；SDK 不是 Python 代码沙箱或第三方 Skill 可信证明。
P5 验收：python scripts/check_phase.py P5；P6 接入见 docs/langgraph.md。

P6 加固新增 renew(tool_id, context, expected_digest=..., expected_version=...)：仅原先批准
且过期的注册可续期，原绑定/元数据从内部快照取得，调用方提供当前注册权限和预期版本/摘要。
新事件重新走 Gate0，成功才产生新注册代次；不会恢复撤销或失败/待审批记录。过期状态不覆盖
撤销状态；注册/续期与审批在最终发布前重验状态，避免慢检查覆盖并发撤销。
