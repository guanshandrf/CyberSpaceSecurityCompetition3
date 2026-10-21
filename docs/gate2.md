# P4 工具结果安全检查

P4 引入，当前 SDK 0.6.0，P2 schema 1.0 保持不变。Gate2.after_tool(event, context, call=...) 校验完整
调用/结果关联，并执行规则插件和 Redactor；evaluate 满足 Gate Protocol，但只检查结果与
上下文 envelope，正式结果通道必须使用 after_tool/ResultHandler 并提供原调用。

RuleResultDetector 检查指令覆盖、system/developer/user 伪装、外发凭据请求和中文指令。
普通研究介绍、嵌入的攻击引用和明确的否定外发建议不会仅因安全关键词被全部阻断。
规则只覆盖明确样例，不是完整语义防护，存在误报/漏报；插件可替换/扩展且无模型依赖。
原生 JSON 和 JSON 编码字符串都检查嵌套字段；深度/大小与 P2 有限 JSON 限制保持。

Redactor 对密钥模式、认证串、口令赋值、敏感 JSON 字段和后端显式配置的 secrets 脱敏。
默认不读取环境变量，也不保证识别任意敏感文本。脱敏导致键冲突或关键检查异常时 BLOCK。
Detector findings 优先 BLOCK；无风险但内容变更为 SANITIZE，必须提供非空替换值；
其余为 ALLOW。异常/非法结果/关联/决策/审计故障均不回退原文。

ResultHandler.after_tool 返回 HandledResult，raw_event 是仅供可信后端使用的原始事件，
safe_event 是可交给 Adapter 的独立副本；repr 隐藏全部内容。BLOCK safe_event 只包含
固定 guard.result_blocked 错误；SANITIZE 只含 replacement_content，来源固定标记为
agentguard.gate2。handle_execution 将真实 GuardedExecutor 的正常/错误/未执行结果都
纳入该通道，非 JSON/超限输出转安全错误，不向模型暴露异常正文。

SQLiteAudit 记录真实 gate2 动作和白名单原因，内容、结果、异常和原始身份不落库。
Gate2 不能撤销工具副作用，raw_event 不能发给模型或普通日志。P3 execute 的原始 value
仍供后端使用；P6 Adapter 才将完整 Agent 路径强制改为只消费 safe_event。

本阶段未实现 Gate0/注册准入或 LangGraph 接入。离线验收：python scripts/check_phase.py P4。

## P6 安全加固的检测覆盖

在既有规则上增加 Unicode NFKC/零宽格式字符规范化、指令/动作/敏感目标或外发目的地的组合
判断、中英文角色与优先级伪装、工具调用诱导。否定与研究引用只在当前分句作用，不为后续
恶意动作提供整篇豁免；Detector 仍只输出 Finding，不决定执行权限，不依赖外部模型。

fixtures/p6-result-intents.json 的 48 条中英文人工对照样本包含 24 恶意、24 正常，覆盖同样的
文件/凭据/角色/工具词汇在不同意图和上下文中的使用。另有编码变体、嵌套内容和实际图中
结果隔离测试。这是专门针对已知漏检的回归语料，**不是独立语义能力评估或 Benchmark**。
该实现仍是有限的组合意图规则，不保证理解任意语义改写；新隐喻、多语言、跨文段指代、
编码载荷或伪装引用仍可能漏检，正常操作文档也可能误报。不得把有限样本结果外推为完整防护。

P6 后续小范围修复不再以否定前缀豁免整个分句：逗号、冒号或连接词引入的新独立请求继续
检测，连续否定建议逐项处理；保留普通否定目标列表及 or 并列。仍是有限规则，不是完整
语法解析；含糊并列可能保守误报。测试及真实 LangGraph 路径复核见
`reports/P6-negation-fix-acceptance.md`。

P6 转折作用域补丁进一步识别“然而”和后接明确指令的“但”，并在单个分句开头移除有限的
“安全建议/提示/提醒：”或 Safety advice/tip 标签后重新检查内容。标签不赋予信任或豁免：
肯定指令、转折后的恶意动作仍须阻断，明确否定建议可正常返回。截图原样输入、对照变体、
编码内容及实际 LangGraph 路径测试见 `reports/P6-contrast-negation-fix-acceptance.md`。
