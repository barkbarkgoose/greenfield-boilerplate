<script setup lang="ts">
// Profile & settings. The boilerplate's AI provider and API key settings are
// hidden here on purpose: this site doesn't use AI. The backend still accepts
// them (/api/v1/auth/settings/), so they can come back without a migration.
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { SUPPORTED_LOCALES, setLocale } from '@/i18n'
import type { Locale } from '@/i18n'

const { t, locale } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

const user = computed(() => authStore.user)
const initials = computed(() => {
  const name = user.value?.name?.trim()
  if (name) {
    return name
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0])
      .join('')
      .toUpperCase()
  }
  return user.value?.email?.charAt(0).toUpperCase() || 'U'
})

function chooseLanguage(value: Locale) {
  setLocale(value)
}

function logout() {
  authStore.logout()
  router.push({ name: 'home' })
}
</script>

<template>
  <div class="settings-page px-4 py-10 sm:px-6">
    <div class="mx-auto max-w-3xl">
      <header class="mb-8">
        <h1 class="text-3xl font-bold tracking-tight text-slate-950">{{ t('settings-page__title') }}</h1>
      </header>

      <div class="grid gap-6">
        <section class="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <div class="flex items-center gap-4">
            <span class="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-slate-900 text-xl font-bold text-white">
              {{ initials }}
            </span>
            <div class="min-w-0">
              <h2 class="truncate text-xl font-semibold text-slate-950">{{ user?.name || t('settings-page__profile-fallback') }}</h2>
              <p class="truncate text-sm text-slate-500">{{ user?.email }}</p>
            </div>
          </div>
          <p class="mt-6 text-sm text-slate-500">{{ t('settings-page__profile-hint') }}</p>
        </section>

        <section class="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <h2 class="text-lg font-semibold text-slate-950">{{ t('settings-page__language-title') }}</h2>
          <p class="mt-1 text-sm text-slate-500">{{ t('settings-page__language-hint') }}</p>
          <div class="mt-4 flex flex-wrap gap-2" role="radiogroup" :aria-label="t('settings-page__language-title')">
            <button
              v-for="option in SUPPORTED_LOCALES"
              :key="option"
              type="button"
              role="radio"
              :aria-checked="locale === option"
              :lang="option"
              class="rounded-xl px-4 py-2 text-sm font-semibold ring-1"
              :class="locale === option ? 'bg-slate-900 text-white ring-slate-900' : 'text-slate-700 ring-slate-300 hover:bg-slate-50'"
              @click="chooseLanguage(option)"
            >
              {{ t(`language-toggle__option--${option}`) }}
            </button>
          </div>
        </section>

        <section class="flex flex-wrap items-center justify-between gap-3 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <p class="text-sm text-slate-600">{{ t('settings-page__logout-hint') }}</p>
          <button type="button" class="rounded-xl px-4 py-2 text-sm font-semibold text-red-700 ring-1 ring-red-200 hover:bg-red-50" @click="logout">
            {{ t('app-nav__menu-item--logout') }}
          </button>
        </section>
      </div>
    </div>
  </div>
</template>
