import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'

// Synthetic component fixtures only; actual API/Graph coverage is in P7.e2e.test.js.
const sid = 'public-session'
const data = (event, fields, sequence) => ({ event, sequence, data: { session_id: sid, trace_id: 'trace-one', ...fields } })
const record = (gate, action, execution, id, sequence) => data('audit', {
  name: 'read_file', gate, action, execution, tool_call_id: id, stage: 'handled',
  duration_ms: 1.2, risk: action === 'BLOCK' ? 'high' : 'none',
  reason_codes: ['checks.passed'], matched_policies: ['policy.result'],
}, sequence)
const transcript = [
  data('user', { content: '<img src=x onerror="window.pwned=1"> sk-[REDACTED]' }, 1),
  data('tool_call', { name: 'read_file', tool_call_id: 'call-one' }, 2),
  record('gate1', 'BLOCK', 'not_executed', 'call-one', 3),
  record('gate2', 'ALLOW', 'not_applicable', 'call-one', 4),
  data('tool_call', { name: 'read_file', tool_call_id: 'call-two' }, 5),
  record('gate1', 'ALLOW', 'executed', 'call-two', 6),
  data('message', { content: '<script>window.pwned=1</script>Safe reply' }, 7),
  data('done', { ok: true }, 8),
]
function api(overrides = {}) {
  return {
    health: vi.fn(async () => ({ guard: 'enabled', mode: 'protected' })),
    sessions: vi.fn(async () => ({ sessions: [{ session_id: sid, active: true }] })),
    history: vi.fn(async () => ({ events: [], active: true })),
    create: vi.fn(async () => ({ session_id: sid })),
    stream: vi.fn(async () => {}), ...overrides,
  }
}
const wrappers = []
async function render(backend) {
  const wrapper = mount(App, { props: { api: backend }, attachTo: document.body })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); document.body.innerHTML = '' })

describe('P7 protected chat', () => {
  it('loads sessions and restores both independent tool audit cards', async () => {
    const wrapper = await render(api({ history: vi.fn(async () => ({ events: transcript, active: true })) }))
    expect(wrapper.findAll('.turn')).toHaveLength(1)
    expect(wrapper.findAll('.audit-card')).toHaveLength(2)
    expect(wrapper.findAll('.tool-summary')[0].text()).toContain('未执行')
    expect(wrapper.findAll('.tool-summary')[1].text()).toContain('已执行')
    expect(wrapper.find('.trace-line').text()).toContain('trace-one')
    expect(wrapper.find('.trace-line').text()).toContain('call-one')
  })
  it('hides audit details without changing the request or protected execution feedback', async () => {
    const backend = api({ stream: vi.fn(async (id, text, receive) => transcript.forEach(receive)) })
    const wrapper = await render(backend)
    await wrapper.get('[role="switch"]').trigger('click')
    await wrapper.get('textarea').setValue('public message')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(backend.stream.mock.calls[0].slice(0, 2)).toEqual([sid, 'public message'])
    expect(wrapper.find('.audit-card').exists()).toBe(false)
    expect(wrapper.find('.tool-summary').text()).toContain('未执行')
    expect(wrapper.text()).toContain('防护已启用')
    await wrapper.get('[role="switch"]').trigger('click')
    expect(wrapper.findAll('.audit-card')).toHaveLength(2)
  })
  it('renders hostile user, model and tool labels as text without HTML execution', async () => {
    const wrapper = await render(api({ history: vi.fn(async () => ({ events: transcript, active: true })) }))
    expect(wrapper.text()).toContain('<img src=x')
    expect(wrapper.text()).toContain('<script>')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(window.pwned).toBeUndefined()
  })
  it('never enables chat on a baseline backend', async () => {
    const backend = api({ health: async () => ({ guard: 'not_implemented', baseline_enabled: true }) })
    const wrapper = await render(backend)
    expect(wrapper.get('textarea').element.disabled).toBe(true)
    expect(backend.sessions).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('后端启用保护模式')
  })
  it('keeps archived sessions read-only', async () => {
    const wrapper = await render(api({ history: async () => ({ events: transcript, active: false }) }))
    expect(wrapper.text()).toContain('该会话已归档')
    expect(wrapper.get('textarea').element.disabled).toBe(true)
  })
  it('labels unapproved REVIEW as not executed instead of successful execution', async () => {
    const review = [data('tool_call', { name: 'read_file', tool_call_id: 'pending' }, 1),
      record('gate1', 'REVIEW', 'not_executed', 'pending', 2), data('done', { ok: true }, 3)]
    const wrapper = await render(api({ history: async () => ({ events: review, active: true }) }))
    expect(wrapper.find('.tool-summary').text()).toContain('未执行')
    expect(wrapper.find('.audit-card').text()).toContain('待审批')
  })
  it('reports stream interruption without automatic retry or a claim that tools did not execute', async () => {
    const backend = api({ stream: vi.fn(async (id, text, receive) => {
      receive(data('tool_call', { name: 'read_file', tool_call_id: 'unconfirmed' }, 1))
      throw new Error('sensitive internal error')
    }) })
    const wrapper = await render(backend)
    await wrapper.get('textarea').setValue('hello'); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(backend.stream).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('连接中断或请求失败')
    expect(wrapper.text()).not.toContain('sensitive internal error')
    expect(wrapper.text()).not.toContain('未执行')
  })
  it('creates a new backend session and reloads its persisted state', async () => {
    const backend = api()
    const wrapper = await render(backend)
    await wrapper.get('.new-session').trigger('click'); await flushPromises()
    expect(backend.create).toHaveBeenCalledTimes(1)
    expect(backend.history).toHaveBeenCalledTimes(2)
  })
  it('shows session history failures without enabling writes to an unknown state', async () => {
    const wrapper = await render(api({ history: async () => { throw new Error('private body') } }))
    expect(wrapper.text()).toContain('历史记录加载失败')
    expect(wrapper.get('textarea').element.disabled).toBe(true)
    expect(wrapper.text()).not.toContain('private body')
  })
})
