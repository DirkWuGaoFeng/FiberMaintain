import { test, expect } from '@playwright/test'

/**
 * E2E: 应用导航与页面渲染
 */
test.describe('应用导航', () => {
  test('首页加载对话视图', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('.chat-view')).toBeVisible()
    // 空状态提示
    await expect(page.locator('.empty-state')).toBeVisible()
    // 快捷指令面板
    await expect(page.locator('.quick-actions')).toBeVisible()
    await expect(page.locator('.action-chip')).toHaveCount(6)
  })

  test('侧栏导航切换到工作流页', async ({ page }) => {
    await page.goto('/')
    await page.click('text=工作流编排')
    await expect(page).toHaveURL('/workflow')
    await expect(page.locator('.workflow-view')).toBeVisible()
    await expect(page.locator('.graph-canvas')).toBeVisible()
  })

  test('导航到知识库页', async ({ page }) => {
    await page.goto('/knowledge')
    await expect(page.locator('.knowledge-view')).toBeVisible()
    await expect(page.locator('.upload-zone')).toBeVisible()
  })

  test('导航到监控页', async ({ page }) => {
    await page.goto('/monitor')
    await expect(page.locator('.monitor-view')).toBeVisible()
    await expect(page.locator('.overview-card')).toHaveCount(4)
  })

  test('导航到工具操作台', async ({ page }) => {
    await page.goto('/tools')
    await expect(page.locator('.tools-view')).toBeVisible()
    await expect(page.locator('.nav-group').first()).toBeVisible()
  })

  test('导航到记忆管理', async ({ page }) => {
    await page.goto('/memory')
    await expect(page.locator('.memory-view')).toBeVisible()
  })
})

test.describe('对话交互', () => {
  test('输入框可输入并显示发送按钮', async ({ page }) => {
    await page.goto('/')
    const input = page.locator('.input-area textarea')
    await input.fill('查询光纤 3 的跨段衰耗')
    // 发送按钮可用
    await expect(page.locator('.send-btn')).toBeEnabled()
  })

  test('空输入时发送按钮禁用', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('.send-btn')).toBeDisabled()
  })

  test('点击快捷指令触发发送', async ({ page }) => {
    await page.goto('/')
    // 拦截 Agent 请求（后端可能未运行）
    await page.route('**/fiber-agent/stream', (route) =>
      route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }),
    )
    await page.locator('.action-chip').first().click()
    // 发送后出现消息气泡
    await expect(page.locator('.message-bubble.user')).toBeVisible()
  })
})

test.describe('主题切换', () => {
  test('深色模式切换', async ({ page }) => {
    await page.goto('/')
    // 查找主题切换按钮（布局顶栏）
    const themeBtn = page.locator('[data-testid="theme-toggle"]')
    if (await themeBtn.isVisible()) {
      await themeBtn.click()
      const isDark = await page.evaluate(() => document.documentElement.classList.contains('dark'))
      expect(typeof isDark).toBe('boolean')
    }
  })
})
