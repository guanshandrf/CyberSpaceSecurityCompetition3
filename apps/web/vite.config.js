import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

const phase = process.env.AGENTGUARD_CHECK_PHASE === 'P1' ? 'P1' : 'P0'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.js'],
    setupFiles: ['./src/test-setup.js'],
    reporters: ['default', 'junit'],
    outputFile: { junit: `../../reports/generated/${phase}-web-junit.xml` },
  },
})
