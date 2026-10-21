import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App.vue'

const wrappers = []
afterEach(() => wrappers.splice(0).forEach(w => w.unmount()))
async function render({ real = true, events = [] } = {}) {
  const api = {
    health: async () => ({ guard: 'enabled', mode: 'protected' }),
    models: async () => ({ default_provider: 'fake', selectable: true,
      models: [{ id: 'fake', available: true }, { id: 'deepseek', available: real }],
      limits: { max_output_tokens: 256, max_total_calls: 16, used_calls: 0 } }),
    sessions: async () => ({ sessions: [{ session_id: 'session.1', active: true }] }),
    history: async () => ({ active: true, events, provider: 'fake' }),
    create: vi.fn(async provider => ({ session_id: 'session.1', provider })),
    stream: vi.fn(async () => {}),
  }
  const wrapper = mount(App, { props: { api } }); wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, api }
}
it('explains Fake echo in an existing session, not just on the welcome screen', async () => {
  const { wrapper } = await render()
  expect(wrapper.get('.model-notice').text()).toContain('不会生成真实问答')
  expect(wrapper.get('.model-selector').text()).toContain('离线 Fake')
})
it('chooses a new DeepSeek session only after explicit fee confirmation', async () => {
  const { wrapper, api } = await render()
  await wrapper.get('.model-selector').trigger('click')
  await wrapper.get('select').setValue('deepseek')
  expect(wrapper.get('.apply-model').element.disabled).toBe(true)
  expect(api.create).not.toHaveBeenCalled()
  await wrapper.get('[aria-label="确认真实 API 费用"]').setValue(true)
  await wrapper.get('.apply-model').trigger('click'); await flushPromises()
  expect(api.create).toHaveBeenCalledExactlyOnceWith('deepseek')
  expect(api.stream).not.toHaveBeenCalled()
  expect(wrapper.get('.model-selector').text()).toContain('真实 API')
  expect(wrapper.text()).toContain('防护已启用')
})
it('disables unavailable real model and never asks for a browser-side API key', async () => {
  const { wrapper } = await render({ real: false })
  await wrapper.get('.model-selector').trigger('click')
  expect(wrapper.get('option[value="deepseek"]').element.disabled).toBe(true)
  expect(wrapper.text()).toContain('请勿在聊天消息中粘贴 Key')
  expect(wrapper.find('input[type="password"]').exists()).toBe(false)
})
it('shows a completed empty answer instead of a blank assistant bubble', async () => {
  const { wrapper } = await render({ events: [
    { sequence: 1, event: 'user', data: { session_id: 'session.1', trace_id: 'trace.1', content: 'hello' } },
    { sequence: 2, event: 'done', data: { session_id: 'session.1', trace_id: 'trace.1', ok: true } },
  ] })
  expect(wrapper.text()).toContain('模型未返回文本回答')
})
it('explains exhausted global budget without suggesting a reset by model switching', async () => {
  const { wrapper } = await render({ events: [
    { sequence: 1, event: 'error', data: { session_id: 'session.1', trace_id: 'trace.1', code: 'total_provider_call_limit' } },
    { sequence: 2, event: 'done', data: { session_id: 'session.1', trace_id: 'trace.1', ok: false } },
  ] })
  expect(wrapper.text()).toContain('切换模型或新建对话不会恢复额度')
})
