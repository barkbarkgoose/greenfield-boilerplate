<script setup lang="ts">
// Switches between English and Spanish. On pages with a Spanish address the
// URL changes too (/book <-> /es/book); elsewhere only the saved choice does.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { setLocale } from '@/i18n'

defineProps<{ dark?: boolean }>()

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()

const next = computed(() => (locale.value === 'es' ? 'en' : 'es'))

function toggle() {
  const target = next.value
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
  <button
    type="button"
    class="language-toggle rounded-lg px-2.5 py-2 text-sm font-medium"
    :class="dark ? 'text-slate-300 hover:text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'"
    :lang="next"
    :aria-label="t('language-toggle__label')"
    @click="toggle"
  >
    <span class="hidden sm:inline">{{ t(`language-toggle__option--${next}`) }}</span>
    <span class="sm:hidden">{{ next.toUpperCase() }}</span>
  </button>
</template>
