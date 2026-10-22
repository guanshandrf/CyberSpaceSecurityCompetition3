import { describe, expect, it } from 'vitest'
import { analyzeSecurity } from './securityAnalysis.js'

const row = (gate, fields = {}) => ({ gate, action: 'ALLOW', execution: 'not_applicable', stage: 'handled', reason_codes: [], risk: 'none', duration_ms: 1, ...fields })
const completed = { done: true }

describe('evidence-based security analysis', () => {
  it('keeps a denied call unexecuted even when its safe error passes Gate 2', () => {
    const report = analyzeSecurity([row('gate1', { action: 'BLOCK', execution: 'not_executed', reason_codes: ['path.denied'] }), row('gate2')], completed)
    expect(report.title).toBe('调用已阻断，工具未执行')
    expect(report.issues[0].name).toBe('授权与资源边界')
    expect(report.issues[0].evidence).toEqual([1])
    expect(report.conclusion).toContain('不代表其他调用或整个会话没有副作用')
  })
  it('never describes Gate 2 blocking as undoing execution', () => {
    const report = analyzeSecurity([row('gate1', { execution: 'executed', stage: 'completed' }), row('gate2', { action: 'BLOCK', reason_codes: ['result.instruction'], risk: 'high' })], completed)
    expect(report.title).toBe('工具已执行，返回内容被阻断')
    expect(report.conclusion).toContain('不能撤销此前工具的副作用')
    expect(report.risk).toBe('高')
    expect(report.issues[0].evidence).toEqual([2])
  })
  it('explains sanitization without consuming original sensitive fields', () => {
    const records = [row('gate1', { execution: 'executed' }), row('gate2', { action: 'SANITIZE', reason_codes: ['result.redacted'], arguments: 'synthetic-private', result: 'synthetic-private', findings: ['synthetic-private'] })]
    const report = analyzeSecurity(records, completed)
    expect(report.title).toContain('返回内容已替换')
    expect(report.conclusion).toContain('仅将安全替换内容')
    expect(JSON.stringify(report)).not.toContain('synthetic-private')
  })
  it('does not turn an ALLOW or missing risk score into proof of safety', () => {
    const report = analyzeSecurity([row('gate1', { execution: 'executed' }), row('gate2')], completed)
    expect(report.title).toContain('审核通过')
    expect(report.risk).toBe('未评分')
    expect(report.riskNote).toContain('不能解释为零风险')
    expect(report.conclusion).toContain('不等于已证明内容绝对安全')
    expect(report.gaps.join(' ')).toContain('缺少可关联的 Gate 0')
  })
  it('does not infer execution from admission, turn completion or a result alone', () => {
    for (const records of [[row('gate1', { stage: 'started', execution: 'admitted' })], [row('gate2')], []]) {
      const report = analyzeSecurity(records, completed)
      expect(report.title).toBe('执行状态待确认')
      expect(report.conclusion).not.toContain('确认工具已进入执行')
    }
  })
  it('preserves execution evidence when a replay or later approval is denied', () => {
    const report = analyzeSecurity([row('gate1', { execution: 'executed' }), row('gate1', { action: 'BLOCK', execution: 'not_executed', reason_codes: ['call.replayed'] })], completed)
    expect(report.title).toContain('存在执行与拒绝记录')
    expect(report.gaps.join(' ')).toContain('不自动判定为零副作用')
    expect(report.issues[0].name).toBe('预算与重复调用')
  })
  it('distinguishes pending approval from permission to run', () => {
    const report = analyzeSecurity([row('gate1', { action: 'REVIEW', execution: 'not_executed', reason_codes: ['approval.required'] })], completed)
    expect(report.title).toBe('等待审批，工具未执行')
    expect(report.coverage[2].status).toBe('未执行工具，无执行结果')
    expect(report.advice.join(' ')).toContain('审批完成前不执行工具')
  })
  it('excludes inherited registration and invalid timing without summing overlapping stages', () => {
    const report = analyzeSecurity([row('gate0', { inherited: true, duration_ms: 100 }), row('gate1', { duration_ms: 2 }), row('gate1', { duration_ms: 5 }), row('gate2', { duration_ms: NaN })], completed)
    expect(report.timing).toBe('2.000–5.000 ms（2 条记录）')
    expect(report.lifecycleCount).toBe(1)
    expect(report.timingNote).toContain('不累加')
    expect(report.evidence[0].stage).toBe('关联注册生命周期')
  })
  it('warns about interruptions and undisclosed policy evidence', () => {
    const report = analyzeSecurity([row('gate1', { reason_codes: ['policy.custom'] })], { done: false, interrupted: true })
    expect(report.gaps.join(' ')).toContain('异常或中断')
    expect(report.gaps.join(' ')).toContain('自定义策略详情未公开')
    expect(report.evidence[0].reasons[0].text).toBe('自定义策略详情未对外公开')
  })
  it('does not claim plain text underwent tool checks', () => {
    const report = analyzeSecurity([], { done: true, noTool: true })
    expect(report.title).toBe('当前未观察到工具调用')
    expect(report.conclusion).toContain('不能将普通文本回复认定为通过')
    expect(report.coverage[1].status).toBe('未观察到工具调用')
    expect(report.evidence).toEqual([])
    expect(report.gaps).toEqual([])
  })
  it('reports execution errors as such even if the error response passes result review', () => {
    const report = analyzeSecurity([row('gate1', { stage: 'error', execution: 'executed' }), row('gate2')], completed)
    expect(report.title).toContain('工具执行异常')
    expect(report.tone).toBe('attention')
  })
})
