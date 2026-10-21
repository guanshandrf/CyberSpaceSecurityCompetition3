<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElButton, ElSwitch, ElTag } from 'element-plus'
import { createClient } from './client.js'
import './style.css'

const props = defineProps({ api: { type: Object, default: () => createClient() } })
const sessions = ref([]), selected = ref(''), events = ref([]), draft = ref('')
const showAudit = ref(true), busy = ref(false), loading = ref(true), error = ref(''), enabled = ref(false)
const active = ref(false), conversation = ref(null)
const modelCatalog = ref(null), currentProvider = ref(''), nextProvider = ref('fake')
const modelPanel = ref(false), realConfirmed = ref(false)
const modelName = id => ({ fake: '离线 Fake', deepseek: 'DeepSeek · 真实 API' }[id] || '模型待确认')
const deepseekAvailable = computed(() => modelCatalog.value?.models?.some(m => m.id === 'deepseek' && m.available))
const modelSelectable = computed(() => modelCatalog.value?.selectable === true)
let loadVersion = 0
const registration = computed(() => events.value.filter(e => e.event === 'audit' && e.data.gate === 'gate0'))
const turns = computed(() => {
  const grouped = new Map()
  for (const e of events.value) {
    if (e.event === 'audit' && e.data.gate === 'gate0') continue
    const key = e.data.trace_id
    if (!grouped.has(key)) grouped.set(key, { trace: key, user: '', reply: '', calls: new Map(), error: '', done: false, provider: '' })
    const turn = grouped.get(key), data = e.data
    if (e.event === 'session') turn.provider = data.provider
    if (e.event === 'user') turn.user = data.content
    if (e.event === 'message') turn.reply = data.content
    if (e.event === 'error') turn.error = data.code
    if (e.event === 'done') turn.done = true
    if (['tool_call', 'tool_result', 'audit'].includes(e.event) && data.tool_call_id) {
      const id = data.tool_call_id
      if (!turn.calls.has(id)) turn.calls.set(id, { id, name: data.name, audits: [], result: null, sequence: e.sequence })
      const call = turn.calls.get(id)
      if (e.event === 'audit') call.audits.push(data)
      if (e.event === 'tool_result') call.result = data.result
    }
  }
  return [...grouped.values()]
})
const canSend = computed(() => enabled.value && active.value && !busy.value && !loading.value && draft.value.trim())
function callState(call, turn) {
  if (call.audits.some(a => a.execution === 'executed')) return '已执行'
  if (call.audits.some(a => a.execution === 'not_executed')) return '未执行'
  return turn.done || !busy.value ? '执行状态未确认' : '检查中'
}
function gates(call) {
  const approved = registration.value.filter(e => e.data.name === call.name && e.sequence <= call.sequence).at(-1)
  return [...(approved ? [{ ...approved.data, inherited: true }] : []), ...call.audits]
}
const actionText = a => ({ ALLOW: '允许', BLOCK: '阻断', REVIEW: '待审批', SANITIZE: '已脱敏' }[a] || '未知')
const riskText = r => ({ none: '未评分', info: '提示', low: '低', medium: '中', high: '高', critical: '严重' }[r] || '未评分')
const errorText = code => ({
  provider_call_limit: '本会话已达到模型调用上限，请新建对话。',
  total_provider_call_limit: '后端共享调用预算已用完，请由后端管理员核对预算。切换模型或新建对话不会恢复额度。',
  provider_error: '模型服务请求失败，请检查后端 Key、网络与额度；未自动重试。',
  tool_call_limit: '本轮工具调用已达到上限。',
  turn_failed: '本轮处理失败，请查看审计确认工具状态。',
}[code] || '本轮未完成，请查看审计确认工具状态。')
async function refreshSessions() { sessions.value = (await props.api.sessions()).sessions }
async function openSession(id) {
  if (busy.value) return
  const version = ++loadVersion
  selected.value = id; active.value = false; loading.value = true; error.value = ''; events.value = []
  try {
    const history = await props.api.history(id)
    if (version !== loadVersion) return
    events.value = history.events; active.value = history.active
    currentProvider.value = history.provider || history.events.find(e => e.event === 'session')?.data.provider || modelCatalog.value?.default_provider || ''
    if (['fake', 'deepseek'].includes(currentProvider.value)) {
      if (nextProvider.value !== currentProvider.value) realConfirmed.value = false
      nextProvider.value = currentProvider.value
    }
  } catch { if (version === loadVersion) error.value = '历史记录加载失败，请重新选择会话。' }
  finally { if (version === loadVersion) loading.value = false }
}
async function newSession() {
  if (busy.value || !enabled.value) return
  const provider = modelSelectable.value ? nextProvider.value : undefined
  if (provider === 'deepseek' && !realConfirmed.value) { modelPanel.value = true; return }
  error.value = ''
  try {
    const created = await props.api.create(provider)
    await refreshSessions(); await openSession(created.session_id)
    currentProvider.value = created.provider || currentProvider.value
    modelPanel.value = false
  } catch { error.value = '创建会话失败，请检查本地服务。' }
}
function receive(e) {
  if (e.data.session_id !== selected.value) throw new Error('Session mismatch')
  if (!e.sequence || !events.value.some(old => old.sequence === e.sequence)) events.value.push(e)
  if (e.event === 'session') currentProvider.value = e.data.provider
  nextTick(() => { if (conversation.value) conversation.value.scrollTop = conversation.value.scrollHeight })
}
async function send() {
  if (!canSend.value) return
  const message = draft.value.trim(); draft.value = ''; busy.value = true; error.value = ''
  try { await props.api.stream(selected.value, message, receive) }
  catch { error.value = '连接中断或请求失败。请刷新历史确认工具状态；不会自动重试。' }
  finally { busy.value = false }
}
onMounted(async () => {
  try {
    const health = await props.api.health()
    enabled.value = health.guard === 'enabled' && health.mode === 'protected'
    if (!enabled.value) { error.value = '请在后端启用保护模式后使用聊天界面。'; return }
    if (props.api.models) {
      modelCatalog.value = await props.api.models()
      currentProvider.value = modelCatalog.value.default_provider
      nextProvider.value = modelCatalog.value.default_provider
    }
    await refreshSessions()
    if (sessions.value.length) await openSession(sessions.value[0].session_id)
  } catch { error.value = '无法连接本地 API，请检查服务是否启动。' }
  finally { loading.value = false }
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">AG</span><h1>AgentGuard<span>安全对话工作台</span></h1></div>
      <ElButton class="new-session" :disabled="!enabled || busy || loading" @click="newSession">＋ 新建对话</ElButton>
      <p class="nav-label">最近会话</p>
      <nav aria-label="会话列表">
        <button v-for="s in sessions" :key="s.session_id" class="session-item" :class="{ selected: selected === s.session_id }"
                :disabled="busy" @click="openSession(s.session_id)">
          <span>对话 {{ s.session_id.slice(0, 8) }}</span><small>{{ s.active ? '本地会话' : '历史 · 只读' }}</small>
        </button>
      </nav>
      <div class="sidebar-foot"><span class="status-dot"></span> 本地实验环境<p>仅保护已接管的工具调用</p></div>
    </aside>
    <main class="workspace">
      <header class="topbar">
        <div><strong>{{ selected ? `对话 ${selected.slice(0, 8)}` : '新的一次安全探索' }}</strong><span class="header-sub">AgentGuard · 受保护对话</span></div>
        <div class="header-controls"><ElTag :type="enabled ? 'success' : 'info'">{{ enabled ? '防护已启用' : '服务未就绪' }}</ElTag>
          <button class="model-selector" aria-label="模型设置" @click="modelPanel = !modelPanel">{{ modelName(currentProvider) }} ▾</button>
          <ElSwitch v-model="showAudit" aria-label="显示安全审计" active-text="显示安全审计" />
        </div>
      </header>
      <section v-if="modelPanel" class="model-panel" role="region" aria-label="模型选择">
        <div><strong>选择新对话的模型</strong><button aria-label="关闭模型设置" @click="modelPanel = false">关闭</button></div>
        <p>每个会话固定使用一个模型。切换会创建新会话，原会话保留原模型与历史，防护始终启用。</p>
        <label>模型 <select v-model="nextProvider" aria-label="新对话模型" :disabled="!modelSelectable || busy" @change="realConfirmed = false">
          <option value="fake" :disabled="!modelCatalog?.models?.some(m => m.id === 'fake' && m.available)">离线 Fake（回显 / 工具演示，不产生费用）</option>
          <option value="deepseek" :disabled="!deepseekAvailable">DeepSeek · 真实 API{{ deepseekAvailable ? '（发送消息会计费）' : '（后端未启用）' }}</option>
        </select></label>
        <p v-if="!deepseekAvailable">真实 API 需后端读取根目录 .env 中的 DEEPSEEK_API_KEY，并启用真实 API 与模型选择。请勿在聊天消息中粘贴 Key。</p>
        <p v-if="!modelSelectable">后端尚未开放模型选择；当前仅能使用后端指定的模型。</p>
        <p v-if="modelCatalog?.limits">输出上限 {{ modelCatalog.limits.max_output_tokens }} token / 次；进程共享预算 {{ modelCatalog.limits.max_total_calls }} 次（含 Fake、工具调用后的模型续答；失败也计数）。</p>
        <label v-if="nextProvider === 'deepseek'" class="model-consent"><input v-model="realConfirmed" type="checkbox" aria-label="确认真实 API 费用">我了解发送消息将调用真实 DeepSeek API 并产生费用。</label>
        <ElButton class="apply-model" type="primary" :disabled="!enabled || busy || loading || !modelSelectable || (nextProvider === 'deepseek' && (!deepseekAvailable || !realConfirmed))" @click="newSession">使用所选模型新建对话</ElButton>
      </section>
      <p v-if="currentProvider === 'fake'" class="model-notice" role="status">当前为离线 Fake：仅回显输入或演示工具调用，不会生成真实问答。点击顶部“离线 Fake”可选择真实 API。</p>
      <div ref="conversation" class="conversation" aria-live="polite" :aria-busy="busy || loading">
        <div v-if="!turns.length" class="welcome">
          <div class="welcome-mark">AG<span>✓</span></div><p class="eyebrow">CONTROLLED TOOLS. CLEAR DECISIONS.</p>
          <h2>每一次调用，都有迹可循。</h2><p>和 Agent 对话，查看工具调用如何经过安全检查。</p>
          <div class="suggestions"><button @click="draft = '你好，请介绍一下自己。'">开始一段对话 <span>↗</span></button>
            <button @click="draft = 'read_file {&quot;path&quot;:&quot;hello.txt&quot;}'">读取沙箱样例 <span>↗</span></button></div>
          <small>当前使用 {{ modelName(currentProvider) }} · 样例文件需放入 input 沙箱</small>
        </div>
        <p v-if="loading" class="inline-status" role="status">正在加载会话…</p>
        <article v-for="turn in turns" :key="turn.trace" class="turn" :data-trace="turn.trace">
          <div v-if="turn.user" class="user-message"><span>你</span><p>{{ turn.user }}</p></div>
          <div class="assistant-message"><div class="avatar">AG</div><div class="answer-body"><strong>AgentGuard</strong>
            <small v-if="turn.provider" class="reply-model">{{ modelName(turn.provider) }}{{ turn.provider === 'fake' ? ' · 演示回显' : '' }}</small>
            <p v-if="turn.reply" class="reply">{{ turn.reply }}</p>
            <p v-else-if="!turn.done && busy" class="inline-status">正在处理<span class="dots">…</span></p>
            <p v-else-if="turn.done && !turn.error" class="inline-status">本轮已结束，模型未返回文本回答；请查看工具状态与审计。</p>
            <div v-if="turn.calls.size" class="tool-progress">
              <div v-for="call in turn.calls.values()" :key="call.id" class="tool-summary">
                <span class="tool-glyph">⌘</span><code>{{ call.name }}</code><span :class="{ denied: callState(call, turn) === '未执行' }">{{ callState(call, turn) }}</span>
              </div>
            </div>
            <section v-if="showAudit && turn.calls.size" class="audit-group" aria-label="工具安全审计">
              <details v-for="call in turn.calls.values()" :key="call.id" class="audit-card">
                <summary><span class="shield">◇</span><strong>{{ call.name }}</strong><span>{{ callState(call, turn) }}</span><span class="expand-label">查看审计 ＋</span></summary>
                <div class="audit-body"><p class="trace-line">trace {{ turn.trace }}<br>call {{ call.id }}</p>
                  <div v-for="(gate, index) in gates(call)" :key="index" class="gate-row" :data-action="gate.action">
                    <div><strong>{{ gate.gate.replace('gate', 'Gate ') }}</strong><ElTag size="small" :type="gate.action === 'BLOCK' ? 'danger' : gate.action === 'REVIEW' ? 'warning' : 'success'">{{ actionText(gate.action) }}</ElTag></div>
                    <p>{{ gate.inherited ? '当前工具注册审查（生命周期记录）' : gate.stage }} · 风险 {{ riskText(gate.risk) }} · {{ gate.duration_ms }} ms</p>
                    <p>原因：{{ gate.reason_codes.join(' · ') }}<br>策略：{{ gate.matched_policies.join(' · ') || '内置硬性校验' }}</p>
                  </div>
                  <p v-if="!call.audits.length">等待安全审计记录…</p>
                </div>
              </details>
            </section>
            <p v-if="turn.error" class="turn-error" role="alert">{{ errorText(turn.error) }}（{{ turn.error }}）</p>
          </div></div>
        </article>
        <details v-if="showAudit && registration.length" class="registration-panel"><summary>工具注册记录 · {{ registration.length }}</summary>
          <p v-for="e in registration" :key="e.sequence">Gate 0 · {{ e.data.name }} · {{ actionText(e.data.action) }} · {{ e.data.reason_codes.join(' · ') }}</p></details>
      </div>
      <footer class="composer-area">
        <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
        <p v-if="selected && !active && !loading" class="archive-note">该会话已归档，只可查看。请新建对话继续。</p>
        <form class="composer" @submit.prevent="send"><textarea v-model="draft" aria-label="消息" placeholder="发送消息，探索受保护的工具调用…"
            maxlength="4096" :disabled="!enabled || !active || loading || busy" @keydown.ctrl.enter.prevent="send"></textarea>
          <div class="composer-bottom"><span><span class="status-dot"></span> 受保护工具通道 <span class="shortcut">Ctrl + Enter 发送</span></span>
            <ElButton native-type="submit" type="primary" aria-label="发送消息" :disabled="!canSend" :loading="busy">{{ busy ? '处理中' : '发送 ↑' }}</ElButton></div>
        </form><p class="disclaimer">审计开关仅控制展示，防护始终由后端执行。模型输出与工具内容均应独立核验。</p>
      </footer>
    </main>
  </div>
</template>
