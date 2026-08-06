/**
 * QuickActions 组件单元测试
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import QuickActions from '@/views/chat/components/QuickActions.vue'
import zhCN from '@/i18n/zh-CN'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN },
})

describe('QuickActions', () => {
  function mountComponent() {
    return mount(QuickActions, {
      global: {
        plugins: [createPinia(), i18n],
      },
    })
  }

  it('渲染 6 个快捷指令', () => {
    const wrapper = mountComponent()
    const chips = wrapper.findAll('.action-chip')
    expect(chips.length).toBe(6)
  })

  it('点击指令触发 select 事件', async () => {
    const wrapper = mountComponent()
    const firstChip = wrapper.find('.action-chip')
    await firstChip.trigger('click')

    expect(wrapper.emitted('select')).toHaveLength(1)
    const emittedText = wrapper.emitted('select')![0][0] as string
    expect(emittedText.length).toBeGreaterThan(0)
  })

  it('展示快捷指令标签文字', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.actions-label').text()).toBe('快捷指令')
  })
})
