import { describe, expect, it, vi } from 'vitest'
import { createClient } from './client.js'

function sse(chunks, contentType = 'text/event-stream') {
  const encoded = chunks.map(c => new TextEncoder().encode(c))
  return new Response(new ReadableStream({ start(c) { encoded.forEach(v => c.enqueue(v)); c.close() } }), {
    headers: { 'content-type': contentType },
  })
}
describe('SSE transport', () => {
  it('parses split CRLF, multibyte Chinese, event IDs and ordered frames', async () => {
    const text = 'id: 1\r\nevent: message\r\ndata: {"content":"离线"}\r\n\r\nid: 2\r\nevent: done\r\ndata: {"ok":true}\r\n\r\n'
    const bytes = new TextEncoder().encode(text)
    const response = new Response(new ReadableStream({ start(c) { for (const byte of bytes) c.enqueue(new Uint8Array([byte])); c.close() } }), { headers: { 'content-type': 'text/event-stream' } })
    const transport = vi.fn(async () => response), received = []
    await createClient(transport).stream('sid', 'hello', e => received.push(e))
    expect(received.map(e => e.sequence)).toEqual([1, 2])
    expect(received[0].data.content).toBe('离线')
    expect(JSON.parse(transport.mock.calls[0][1].body)).toEqual({ message: 'hello' })
    expect(transport.mock.calls[0][0]).toBe('/api/sessions/sid/stream')
  })
  it('rejects an interrupted stream without automatically posting again', async () => {
    const transport = vi.fn(async () => sse(['event: message\ndata: {"content":"partial"}\n\n']))
    await expect(createClient(transport).stream('s', 'x', () => {})).rejects.toThrow('Interrupted stream')
    expect(transport).toHaveBeenCalledTimes(1)
  })
  it.each(['not json', '{}'])('rejects malformed JSON or missing completion: %s', async value => {
    await expect(createClient(async () => sse([`event: message\ndata: ${value}\n\n`])).stream('s', 'x', () => {})).rejects.toThrow()
  })
  it('rejects non-SSE responses', async () => {
    await expect(createClient(async () => sse(['{}'], 'application/json')).stream('s', 'x', () => {})).rejects.toThrow('Invalid stream')
  })
  it('reads all history pages without duplicating the cursor', async () => {
    const transport = vi.fn(async path => Response.json(path.includes('after=0&') ? {
      events: Array.from({ length: 200 }, (_, i) => ({ sequence: i + 1 })), next_after: 200, active: true,
    } : { events: [{ sequence: 201 }], next_after: 201, active: true }))
    const history = await createClient(transport).history('s')
    expect(history.events).toHaveLength(201)
    expect(transport.mock.calls[1][0]).toContain('after=200&limit=200')
  })
  it('does not reflect error response bodies into UI errors', async () => {
    await expect(createClient(async () => new Response('private-body', { status: 503 })).health()).rejects.toThrow('HTTP 503')
  })
})
