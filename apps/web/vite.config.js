import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

const requestedPhase = process.env.AGENTGUARD_CHECK_PHASE
const phase = ['P0', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7'].includes(requestedPhase) ? requestedPhase : 'P7'

const proxy = { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false, rewrite: path => path.replace(/^\/api/, '') } }

export default defineConfig({
  plugins: [vue()],
  server: { proxy, host: '127.0.0.1' },
  preview: { proxy, host: '127.0.0.1' },
  test: {
    environment: 'jsdom',
    env: { AGENTGUARD_REPOSITORY_ROOT: fileURLToPath(new URL('../../', import.meta.url)) },
    include: phase === 'P7' ? ['src/**/*.test.js'] : ['src/App.test.js'],
    setupFiles: ['./src/test-setup.js'],
    reporters: ['default', 'junit'],
    outputFile: { junit: `../../reports/generated/${phase}-web-junit.xml` },
  },
})
