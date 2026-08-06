/**
 * 国际化配置 — vue-i18n 10
 * 默认中文，支持中/英切换，持久化到 localStorage
 */
import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN'
import enUS from './en-US'

export type LocaleKey = 'zh-CN' | 'en-US'

const STORAGE_KEY = 'fiber-agent-locale'

function getDefaultLocale(): LocaleKey {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'en-US' || saved === 'zh-CN') return saved
  return navigator.language.startsWith('zh') ? 'zh-CN' : 'en-US'
}

const i18n = createI18n({
  legacy: false,
  locale: getDefaultLocale(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

/** 切换语言并持久化 */
export function setLocale(locale: LocaleKey) {
  ;(i18n.global.locale as unknown as { value: LocaleKey }).value = locale
  localStorage.setItem(STORAGE_KEY, locale)
  document.documentElement.lang = locale === 'zh-CN' ? 'zh' : 'en'
}

export function getLocale(): LocaleKey {
  return (i18n.global.locale as unknown as { value: LocaleKey }).value
}

export default i18n
