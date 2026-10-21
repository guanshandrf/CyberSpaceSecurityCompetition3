import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
// Preserve the historical P0 component's exact assertions as the P7 app replaces it.
import App from './P0Shell.vue'

describe('P0 shell', () => {
  it('mounts Vue and Element Plus and identifies its unimplemented status', () => {
    const wrapper = mount(App)
    expect(wrapper.get('h1').text()).toBe('AgentGuard')
    expect(wrapper.get('.el-text').text()).toContain('尚未实现安全防护')
    expect(wrapper.find('form').exists()).toBe(false)
    wrapper.unmount()
  })

  it('blocks network requests in the offline test environment', () => {
    expect(() => fetch('https://example.invalid')).toThrow('forbid network')
  })
})
