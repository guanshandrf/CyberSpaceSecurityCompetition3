import { reasonHelp, stageHelp } from './auditDetails.js'

const levels = ['none', 'info', 'low', 'medium', 'high', 'critical']
const riskNames = { none: '未评分', info: '提示', low: '低', medium: '中', high: '高', critical: '严重' }
const actions = { ALLOW: '允许', BLOCK: '阻断', REVIEW: '待审批', SANITIZE: '替换 / 脱敏' }
const categories = [
  ['授权与资源边界', ['permission.denied', 'resource.denied', 'task.denied', 'path.denied'], '调用触及后端授权或沙箱边界；不能仅据此判定用户具有恶意。', '核对任务需要的资源；确需调整时由后端配置最小权限，不绕过执行器。'],
  ['调用合法性与关联', ['schema.invalid', 'event.invalid', 'tool.unknown', 'tool.mismatch', 'session.mismatch', 'result.invalid', 'result.correlation'], '参数、工具身份或事件关联不符合要求，不能按正常调用继续信任。', '核对工具定义和调用关联；修正调用格式后重新发起合法请求。'],
  ['预算与重复调用', ['budget.exhausted', 'call.replayed', 'approval.capacity', 'approval.rate_limited'], '命中调用资源或重放约束；这类拒绝不等同于已发现提示注入。', '检查重复请求或预算使用情况，不通过重放旧调用或切换会话绕过限制。'],
  ['审批与授权状态', ['approval.required', 'approval.denied', 'approval.expired', 'approval.mismatch', 'context.invalid', 'context.changed'], '调用需要审批或当前授权状态不能继续使用。', '等待可信后端审批或重新校验授权，审批完成前不执行工具。'],
  ['工具注册信任', ['registry.review', 'registry.denied', 'registry.expired', 'registry.revoked', 'registry.unknown', 'registry.mismatch', 'registry.changed', 'registry.metadata', 'registry.permission', 'registry.source', 'registry.capability', 'registry.name_conflict', 'registry.capacity'], '工具注册、来源、元数据或生命周期存在限制；静态元数据不能证明工具代码安全。', '由后端核验工具来源、版本和权限；变更或过期后重新经过 Gate 0 审查。'],
  ['返回内容指令注入', ['result.instruction'], '返回内容命中当前注入检测规则，可能试图影响模型指令或后续工具行为；不是对攻击意图的最终证明。', '核验工具内容来源，不把被阻断的原文重新粘贴给模型执行。'],
  ['敏感信息暴露', ['result.redacted'], '返回内容命中敏感信息脱敏规则；公开审计不包含敏感原文。', '仅使用审核后的替换内容；需要时在受控后端核查来源和凭据状态。'],
  ['检查或审计故障', ['check.failed', 'audit.failed'], '关键检查或审计记录出现故障，需要核实执行状态，不能把故障视为通过。', '核对后端故障和工具实际状态；确认前不要自动重试可能产生副作用的操作。'],
  ['策略判定', ['policy.denied', 'policy.custom'], '策略给出限制或隐藏了自定义详情，现有公开记录不足以进一步归因。', '由有权限的维护者核对策略配置；不要从隐藏详情推测具体攻击内容。'],
]

// Presentation only: consumes whitelisted audit fields, never prompts, arguments or results.
export function analyzeSecurity(records, { done = false, interrupted = false, noTool = false } = {}) {
  const rows = noTool ? [] : records.filter(r => ['gate0', 'gate1', 'gate2'].includes(r.gate))
  const byGate = gate => rows.filter(r => r.gate === gate)
  const g1 = byGate('gate1'), g2 = byGate('gate2'), lastResult = g2.at(-1)
  const executed = g1.some(r => r.execution === 'executed')
  const denied = g1.some(r => r.action === 'BLOCK' && r.execution === 'not_executed')
  const review = g1.some(r => r.action === 'REVIEW' && r.execution === 'not_executed')
  const failed = g1.some(r => r.stage === 'error')
  const mixed = executed && (denied || review)
  let title = '执行状态待确认', tone = 'unknown'
  let conclusion = '尚无记录确认工具执行或拒绝，不能推定安全检查已经通过。'
  if (executed) {
    title = failed ? '工具已执行，执行过程出现异常' : '工具已执行'
    conclusion = 'Gate 1 的执行记录确认工具已进入执行；任务是否成功需结合实际业务结果判断。'
    if (lastResult?.action === 'BLOCK') {
      title = '工具已执行，返回内容被阻断'; tone = 'blocked'
      conclusion += ' Gate 2 阻止原始结果进入模型，但不能撤销此前工具的副作用。'
    } else if (lastResult?.action === 'SANITIZE') {
      title = '工具已执行，返回内容已替换'; tone = 'sanitized'
      conclusion += ' Gate 2 仅将安全替换内容交给模型。'
    } else if (lastResult?.action === 'ALLOW') {
      title = failed ? '工具执行异常，返回内容审核通过' : '工具已执行，返回内容审核通过'
      tone = failed ? 'attention' : 'observed'
      conclusion += ' 当前规则允许审核后的结果返回，这不等于已证明内容绝对安全。'
    }
  } else if (denied || review) {
    title = denied ? '调用已阻断，工具未执行' : '等待审批，工具未执行'
    tone = denied ? 'blocked' : 'review'
    conclusion = 'Gate 1 的未执行记录确认该调用未执行真实工具；不代表其他调用或整个会话没有副作用。'
  }
  if (mixed) {
    title = '存在执行与拒绝记录，需核对调用过程'; tone = 'attention'
    conclusion += ' 同一调用关联下同时出现执行和拒绝 / 审批记录，不能以拒绝记录覆盖已经发生的执行。'
  }
  if (noTool) {
    title = '当前未观察到工具调用'; tone = 'unknown'
    conclusion = '本轮没有可关联的工具调用，不能将普通文本回复认定为通过 Gate 1 / Gate 2 安全审核。工具注册属于独立生命周期。'
  }
  const highest = rows.reduce((level, r) => levels.indexOf(r.risk) > levels.indexOf(level) ? r.risk : level, 'none')
  const evidence = rows.map((r, i) => ({
    id: i + 1, gate: r.gate.replace('gate', 'Gate '), action: actions[r.action] || '未知判定',
    stage: r.inherited ? '关联注册生命周期' : stageHelp(r.stage), timestamp: r.timestamp || '未提供时间',
    reasons: [...new Set(r.reason_codes || [])].map(code => ({ code, text: reasonHelp(code) })),
  }))
  const issues = categories.flatMap(([name, codes, meaning, advice]) => {
    const hits = evidence.filter(e => e.reasons.some(r => codes.includes(r.code)))
    return hits.length ? [{ name, meaning, advice, evidence: hits.map(e => e.id) }] : []
  })
  const coverage = ['gate0', 'gate1', 'gate2'].map(gate => {
    const found = byGate(gate)
    return { gate: gate.replace('gate', 'Gate '), count: found.length,
      status: noTool ? gate === 'gate0' ? '生命周期另见注册记录' : '未观察到工具调用' : found.length ? '已有审计证据' : gate === 'gate2' && !executed && (denied || review) ? '未执行工具，无执行结果' : '缺少关联记录',
      note: gate === 'gate0' ? '引用注册生命周期，不能替代本次调用授权。' : gate === 'gate1' ? '整体判定记录不等于每个子检查都有独立证据。' : '审核工具结果，不审核全部用户输入或模型文本。' }
  })
  const gaps = []
  if (!noTool && !byGate('gate0').length) gaps.push('缺少可关联的 Gate 0 注册证据，无法从该报告确认注册状态。')
  if (!noTool && !g1.length) gaps.push('缺少 Gate 1 记录，无法确认调用前审查结论。')
  if (!noTool && !lastResult && (executed || !(denied || review))) gaps.push('缺少 Gate 2 记录，无法确认返回内容是否完成审核。')
  if (!done || interrupted) gaps.push(interrupted ? '本轮异常或中断；当前报告可能不完整，请刷新历史核实。' : '本轮尚未结束，报告随新审计记录更新。')
  if (mixed) gaps.push('需要逐条核对执行与拒绝记录的先后关系，不自动判定为零副作用。')
  if (rows.some(r => r.reason_codes?.includes('policy.custom'))) gaps.push('自定义策略详情未公开，无法从展示字段推导具体检测过程。')
  const durations = rows.filter(r => !r.inherited && !(r.gate === 'gate0' && r.duration_ms === 0)).map(r => r.duration_ms).filter(n => typeof n === 'number' && Number.isFinite(n) && n >= 0)
  return {
    title, tone, conclusion, evidence, issues, coverage, gaps,
    risk: riskNames[highest],
    riskNote: highest === 'none' ? '记录未提供风险发现等级，不能解释为零风险。' : '取所列审计记录的最高发现等级，不是攻击成功概率或综合安全评分。',
    recordCount: rows.length, lifecycleCount: rows.filter(r => r.inherited).length,
    timing: durations.length ? `${Math.min(...durations).toFixed(3)}–${Math.max(...durations).toFixed(3)} ms（${durations.length} 条记录）` : '无独立计时记录',
    timingNote: '为审计记录耗时范围，阶段可能重叠；不累加为总检查耗时，也不等于端到端延迟。',
    advice: noTool ? ['普通文本回答仍需独立核验；实际使用工具时可查看该调用的审查证据。'] : issues.length ? [...new Set(issues.map(i => i.advice))] : ['核对任务实际结果，继续使用受保护工具通道；当前没有可公开解释的限制类原因，不代表所有威胁已被排除。'],
  }
}
