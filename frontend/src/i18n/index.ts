// Site translations. Text lives in ./locales/en.json and ./locales/es.json as
// flat BEM-style keys (block__element--modifier) named after where the text
// appears, e.g. `intake-vehicle__vin-label`. See the README's "Translations".
import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import es from './locales/es.json'

export type MessageSchema = typeof en
// Compile-time guard: Spanish must define every English key.
const esMessages: MessageSchema = es

export const SUPPORTED_LOCALES = ['en', 'es'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

const STORAGE_KEY = 'locale'

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

function storedLocale(): Locale | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return isLocale(value) ? value : null
  } catch {
    return null
  }
}

// Saved choice first, then the browser's language.
function initialLocale(): Locale {
  const browser = typeof navigator !== 'undefined' ? navigator.language?.toLowerCase() : ''
  return storedLocale() ?? (browser?.startsWith('es') ? 'es' : 'en')
}

export const i18n = createI18n<[MessageSchema], Locale, false>({
  legacy: false,
  locale: initialLocale(),
  fallbackLocale: 'en',
  messages: { en, es: esMessages }
})

export function currentLocale(): Locale {
  return i18n.global.locale.value
}

export function setLocale(locale: Locale): void {
  i18n.global.locale.value = locale
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // Private mode etc.: the choice just won't be remembered.
  }
  if (typeof document !== 'undefined') document.documentElement.lang = locale
}

// BCP 47 tag for Intl number/date formatting.
export function intlLocale(): string {
  return currentLocale() === 'es' ? 'es-US' : 'en-US'
}
