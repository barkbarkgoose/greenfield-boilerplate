<script setup lang="ts">
// Switches between English and Spanish. On pages with a Spanish address the
// URL changes too (/book <-> /es/book); elsewhere only the saved choice does.
// A globe icon plus a two-way switch: both languages are visible at once (there
// are only ever two), so there's no ambiguity about which one is "current".
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { SUPPORTED_LOCALES, setLocale } from '@/i18n'
import type { Locale } from '@/i18n'

defineProps<{ dark?: boolean }>()

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()

function select(target: Locale) {
  if (target === locale.value) return
  setLocale(target)
  if (route.meta.localized) {
    router.replace({
      name: route.name!,
      params: { ...route.params, locale: target === 'es' ? 'es' : '' },
      query: route.query,
      hash: route.hash
    })
  }
}
</script>

<template>
  <div
    class="language-toggle flex items-center gap-0.5 rounded-lg p-1"
    :class="dark ? 'bg-white/10' : 'bg-slate-100'"
    role="radiogroup"
    :aria-label="t('language-toggle__label')"
  >
    <svg
      class="ml-1 h-4 w-4 shrink-0"
      :class="dark ? 'text-slate-400' : 'text-slate-500'"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.6"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" />
      <path stroke-linecap="round" d="M3.5 9h17M3.5 15h17" />
      <path stroke-linecap="round" d="M12 3c2.4 2.4 3.6 5.6 3.6 9s-1.2 6.6-3.6 9c-2.4-2.4-3.6-5.6-3.6-9S9.6 5.4 12 3z" />
    </svg>
    <button
      v-for="option in SUPPORTED_LOCALES"
      :key="option"
      type="button"
      role="radio"
      :aria-checked="locale === option"
      :aria-label="t(`language-toggle__option--${option}`)"
      :lang="option"
      class="rounded-md px-2 py-1 text-xs font-bold uppercase tracking-wide transition-colors"
      :class="
        locale === option
          ? dark
            ? 'bg-slate-700 text-white'
            : 'bg-white text-slate-900 shadow-sm'
          : dark
            ? 'text-slate-400 hover:text-white'
            : 'text-slate-500 hover:text-slate-900'
      "
      @click="select(option)"
    >
      {{ option }}
    </button>
  </div>
</template>
