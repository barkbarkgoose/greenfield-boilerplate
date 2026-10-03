// Per-page <title>, description, <html lang> and hreflang links. Pages with a
// Spanish address (/es/...) are marked `meta.localized` in the router.
import type { RouteLocationNormalized } from 'vue-router'
import { business } from '@/config/business'
import { currentLocale, i18n } from '@/i18n'

function setLink(hreflang: string, href: string) {
  let link = document.head.querySelector<HTMLLinkElement>(`link[rel="alternate"][hreflang="${hreflang}"]`)
  if (!link) {
    link = document.createElement('link')
    link.rel = 'alternate'
    link.hreflang = hreflang
    document.head.appendChild(link)
  }
  link.href = href
}

function clearLinks() {
  document.head.querySelectorAll('link[rel="alternate"][hreflang]').forEach((link) => link.remove())
}

export function applyPageMeta(route: RouteLocationNormalized) {
  const { t, te } = i18n.global
  const titleKey = `page-meta__title--${String(route.name)}`
  const descriptionKey = `page-meta__description--${String(route.name)}`
  document.documentElement.lang = currentLocale()
  document.title = te(titleKey) ? `${t(titleKey)} · ${business.name}` : business.name

  const description = document.head.querySelector<HTMLMetaElement>('meta[name="description"]')
  if (description && te(descriptionKey)) description.content = t(descriptionKey)

  clearLinks()
  if (route.meta.localized) {
    // Same page in each language, so search engines index both.
    const path = route.path.replace(/^\/es(?=\/|$)/, '') || '/'
    const origin = window.location.origin
    setLink('en', origin + path)
    setLink('es', origin + (path === '/' ? '/es' : `/es${path}`))
    setLink('x-default', origin + path)
  }
}
