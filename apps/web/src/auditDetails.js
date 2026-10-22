// Explain only the backend's redacted decisions; these labels do not run checks.
export const gateHelp = {
  gate0: ['工具注册准入', '审查工具来源、身份、版本、元数据和权限声明，决定是否向模型提供工具。'],
  gate1: ['调用前安全检查', '执行器在调用前检查可信授权、参数、资源范围、预算及防重放约束；仅有效放行才可执行。'],
  gate2: ['返回内容安全检查', '检查工具返回中的指令注入、角色伪装和敏感内容，决定交给模型的安全结果。'],
}
const reasons = {
  'checks.passed': '本次调用的安全检查通过', 'permission.denied': '缺少后端授予的工具权限',
  'resource.denied': '访问资源超出授权范围', 'path.denied': '路径不符合沙箱限制',
  'schema.invalid': '调用参数不符合工具定义', 'budget.exhausted': '工具调用预算已耗尽',
  'call.replayed': '检测到重复调用，拒绝重放', 'approval.required': '需要可信后端审批，当前不能执行',
  'approval.approved': '审批已通过，执行前仍需重验', 'approval.denied': '审批被拒绝',
  'approval.expired': '审批已过期', 'approval.mismatch': '审批与当前调用不匹配',
  'approval.capacity': '审批记录已达到容量限制', 'approval.rate_limited': '审批创建过于频繁',
  'context.invalid': '可信上下文无效', 'context.changed': '授权上下文发生变化',
  'event.invalid': '工具事件格式无效', 'tool.unknown': '工具不在受控集合中',
  'tool.mismatch': '工具身份与调用不匹配', 'task.denied': '当前任务没有执行授权',
  'session.mismatch': '会话关联校验失败', 'policy.denied': '安全策略拒绝调用',
  'check.failed': '关键安全检查异常，默认拒绝', 'audit.failed': '审计记录失败，默认拒绝',
  'result.instruction': '返回内容被判定存在指令注入风险', 'result.redacted': '返回内容中的敏感信息已脱敏',
  'result.passed': '返回内容通过当前规则检查', 'result.invalid': '返回内容格式无效',
  'result.correlation': '返回内容与原调用关联失败',
  'registry.allowed': '工具注册审查通过', 'registry.approved': '工具注册审批通过',
  'registry.review': '工具注册需要审批', 'registry.denied': '工具注册被拒绝',
  'registry.expired': '工具注册已过期，必须重新审查', 'registry.revoked': '工具授权已撤销',
  'registry.unknown': '工具尚未注册', 'registry.mismatch': '工具与注册记录不匹配',
  'registry.changed': '工具元数据或版本发生变化', 'registry.metadata': '工具元数据不符合要求',
  'registry.permission': '工具声明权限不被允许', 'registry.source': '工具来源不被允许',
  'registry.capability': '工具声明能力不被允许', 'registry.name_conflict': '工具名称存在冲突',
  'registry.capacity': '工具注册数量达到上限', 'policy.custom': '自定义策略详情未对外公开',
}
export const reasonHelp = code => reasons[code] || '该原因未提供公开解释'
export const policyHelp = code => ({ 'policy.configured': '调用授权与配置策略', 'policy.registration': '工具注册准入策略', 'policy.result': '工具返回安全策略', 'policy.custom': '自定义策略（详情隐藏）' }[code] || '策略详情未公开')
export const stageHelp = stage => ({ registered: '注册判定', started: '已准入，准备执行', completed: '工具执行完成', error: '工具执行发生异常', denied: '调用已拒绝', review: '等待审批', handled: '结果处理完成' }[stage] || '审计记录')
export function effectHelp(gate) {
  if (gate.gate === 'gate0') return gate.action === 'ALLOW' ? '工具获准注册；具体调用仍须通过 Gate 1。' : '本次注册未获放行，工具不能凭该记录执行。'
  if (gate.gate === 'gate2') return ({ BLOCK: '原始结果已阻断，不交给模型；此前工具可能已执行，Gate 2 不能撤销副作用。', SANITIZE: '仅安全替换内容交给模型，原始内容不直接返回。', ALLOW: '审核后的结果可交给模型；规则通过不代表内容绝对安全。' }[gate.action] || '结果交付状态待确认。')
  if (gate.execution === 'not_executed') return '该记录表明真实工具未执行，没有通过审批不会放行。'
  if (gate.execution === 'executed') return '该记录确认工具已进入执行；是否完成正常任务需结合模型回复判断。'
  return '仅表示调用已准入，尚不能确认工具已经执行。'
}
