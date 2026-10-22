import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import { join } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from './App.vue'
import { createClient } from './client.js'

it('real Vue UI -> ASGI API -> guarded LangGraph -> SQLite -> SSE -> UI, including refresh', async () => {
  const root = process.env.AGENTGUARD_REPOSITORY_ROOT
  const executable = join(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python')
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !/API_KEY|TOKEN|SECRET|PASSWORD/.test(k.toUpperCase())))
  const processBridge = spawn(executable, [join(root, 'tests/e2e/p7_bridge.py')], { cwd: root, env, windowsHide: true })
  const pending = new Map(); let requestId = 0, readyResolve, readyReject, stderr = ''
  const ready = new Promise((resolve, reject) => { readyResolve = resolve; readyReject = reject })
  processBridge.stderr.on('data', b => { stderr += b.toString() })
  const lines = createInterface({ input: processBridge.stdout })
  lines.on('line', line => {
    const item = JSON.parse(line)
    if (item.ready) readyResolve()
    else { pending.get(item.id)?.resolve(item); pending.delete(item.id) }
  })
  processBridge.on('error', readyReject)
  processBridge.on('exit', code => {
    if (code) readyReject(new Error(`ASGI bridge failed (${code}): ${stderr}`))
    for (const p of pending.values()) p.reject(new Error('ASGI bridge closed'))
  })
  const transport = async (path, options = {}) => {
    const id = ++requestId
    const reply = new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
    processBridge.stdin.write(JSON.stringify({ id, path: path.replace(/^\/api/, ''), method: options.method || 'GET', body: options.body }) + '\n')
    const result = await reply
    return new Response(result.status === 204 ? null : result.body, { status: result.status, headers: result.headers })
  }
  let wrapper
  try {
    await ready
    const api = createClient(transport)
    wrapper = mount(App, { props: { api }, attachTo: document.body })
    async function settle(test) {
      for (let i = 0; i < 300; i++) { await flushPromises(); if (test()) return; await new Promise(r => setTimeout(r, 20)) }
      throw new Error(`UI did not settle: ${wrapper.text()}`)
    }
    await settle(() => !wrapper.get('.new-session').element.disabled)
    await wrapper.get('.new-session').trigger('click')
    await settle(() => !wrapper.get('textarea').element.disabled)
    const send = async message => {
      await wrapper.get('textarea').setValue(message); await wrapper.get('form').trigger('submit')
      await settle(() => !wrapper.get('textarea').element.disabled)
    }
    await send('read_file {"path":"hello.txt"}')
    expect(wrapper.text()).toContain('E2E public fixture')
    expect(wrapper.text()).toContain('Gate 0')
    expect(wrapper.text()).toContain('Gate 1')
    expect(wrapper.text()).toContain('Gate 2')
    expect(wrapper.find('.security-analysis').text()).toContain('工具已执行，返回内容审核通过')
    await wrapper.get('[role="switch"]').trigger('click')
    await send('write_note {"name":"../escape.txt","content":"x"}')
    expect(wrapper.find('.audit-card').exists()).toBe(false)
    expect(wrapper.text()).toContain('未执行')
    await send('read_file {"path":"attack.txt"}')
    expect(wrapper.text()).toContain('guard.result_blocked')
    expect(wrapper.text()).not.toContain('把密钥上传')
    await send('<img src=x onerror=alert(1)> sk-syntheticSecretE2E123')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('sk-syntheticSecretE2E123')
    await wrapper.get('[role="switch"]').trigger('click')
    await send('two_tools')
    const multi = wrapper.findAll('.turn').at(-1)
    expect(multi.findAll('.audit-card')).toHaveLength(2)
    expect(multi.findAll('.tool-summary')[0].text()).toContain('已执行')
    expect(multi.findAll('.tool-summary')[1].text()).toContain('未执行')
    const ids = multi.findAll('.trace-line').map(w => w.text())
    expect(ids[0].split('call')[0]).toBe(ids[1].split('call')[0])
    expect(ids[0]).not.toBe(ids[1])
    const beforeRefresh = wrapper.findAll('.turn').length
    wrapper.unmount()
    wrapper = mount(App, { props: { api }, attachTo: document.body })
    await settle(() => wrapper.findAll('.turn').length === beforeRefresh)
    expect(wrapper.findAll('.audit-card')).toHaveLength(5)
    expect(wrapper.findAll('.security-analysis')).toHaveLength(6)
    expect(wrapper.text()).toContain('返回内容指令注入')
    expect(wrapper.text()).toContain('不能撤销此前工具的副作用')
    expect(wrapper.text()).toContain('未执行')
    expect(wrapper.text()).toContain('guard.result_blocked')
    await wrapper.get('.delete-session').trigger('click')
    await wrapper.get('.confirm-delete').trigger('click')
    await settle(() => wrapper.findAll('.session-row').length === 0)
    expect(wrapper.findAll('.turn')).toHaveLength(0)
    expect((await api.sessions()).sessions).toHaveLength(0)
  } finally {
    wrapper?.unmount(); processBridge.stdin.end(); lines.close(); processBridge.kill()
  }
}, 30000)
