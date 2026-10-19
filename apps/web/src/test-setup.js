import { vi } from 'vitest'

// P0 tests are offline; any attempted external request fails the test.
const denyNetwork = () => { throw new Error('P0 tests forbid network access') }
vi.stubGlobal('fetch', denyNetwork)
vi.stubGlobal('XMLHttpRequest', class { constructor() { denyNetwork() } })
vi.stubGlobal('WebSocket', class { constructor() { denyNetwork() } })
