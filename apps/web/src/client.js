// Same-origin transport only. Display preferences never enter chat requests.
export function createClient(transport = (...args) => fetch(...args)) {
  async function request(path, options) {
    const response = await transport(`/api${path}`, { credentials: 'same-origin', ...options })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response
  }
  async function readHistory(id) {
    const events = []
    let after = 0, page
    do {
      page = await (await request(`/sessions/${encodeURIComponent(id)}/history?after=${after}&limit=200`)).json()
      events.push(...page.events)
      if (page.next_after === after && page.events.length) throw new Error('Invalid history cursor')
      after = page.next_after
    } while (page.events.length === 200)
    return { ...page, events }
  }
  return {
    health: async () => (await request('/health')).json(),
    sessions: async () => (await request('/sessions')).json(),
    create: async () => (await request('/sessions', { method: 'POST' })).json(),
    history: readHistory,
    async stream(id, message, onEvent, signal) {
      const response = await request(`/sessions/${encodeURIComponent(id)}/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }), signal,
      })
      if (!response.headers.get('content-type')?.startsWith('text/event-stream')) throw new Error('Invalid stream')
      const reader = response.body.getReader(), decoder = new TextDecoder()
      let buffer = '', doneSeen = false
      function frame(text) {
        let kind = '', sequence
        const data = []
        for (const line of text.split('\n')) {
          if (line.startsWith('event:')) kind = line.slice(6).trim()
          if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
          if (line.startsWith('id:')) sequence = Number(line.slice(3).trim())
        }
        if (!data.length) return
        if (!['session', 'user', 'tool_call', 'tool_result', 'audit', 'message', 'error', 'done'].includes(kind)) throw new Error('Unknown event')
        const event = { event: kind, data: JSON.parse(data.join('\n')), sequence }
        if (kind === 'done') doneSeen = true
        onEvent(event)
      }
      try {
        while (true) {
          const chunk = await reader.read()
          buffer += decoder.decode(chunk.value, { stream: !chunk.done })
          // Normalize CRLF only after a full line arrives; chunks may split at CR.
          buffer = buffer.replaceAll('\r\n', '\n')
          let boundary
          while ((boundary = buffer.indexOf('\n\n')) !== -1) {
            frame(buffer.slice(0, boundary))
            buffer = buffer.slice(boundary + 2)
          }
          if (buffer.length > 1024 * 1024) throw new Error('Oversized stream frame')
          if (chunk.done) break
        }
        if (buffer.trim()) frame(buffer)
        if (!doneSeen) throw new Error('Interrupted stream')
      } finally { await reader.cancel().catch(() => {}); reader.releaseLock() }
    },
  }
}
