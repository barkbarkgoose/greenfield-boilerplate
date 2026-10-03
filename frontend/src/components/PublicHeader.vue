<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { business } from '@/config/business'
import { useAuthStore } from '@/stores/auth'
import LanguageToggle from '@/components/LanguageToggle.vue'

const { t } = useI18n()
const authStore = useAuthStore()
</script>

<template>
  <header class="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur">
    <div class="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
      <router-link :to="{ name: 'home' }" class="flex items-center gap-2 text-white" :aria-label="t('site-header__home-link', { business: business.name })">
        <span class="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-400 text-slate-900">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M14.7 6.3a4 4 0 00-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 005.2-5.4l-2.6 2.6-2.4-.6-.6-2.4 2.6-2.6z" />
          </svg>
        </span>
        <span class="hidden text-lg font-bold tracking-tight min-[400px]:inline">{{ business.name }}</span>
      </router-link>
      <nav class="flex items-center gap-1 sm:gap-2">
        <LanguageToggle dark />
        <router-link
          :to="{ name: 'home', hash: '#pricing' }"
          class="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-300 hover:text-white sm:block"
        >
          {{ t('site-header__nav-link--pricing') }}
        </router-link>
        <router-link
          :to="{ name: 'book', query: { mode: 'callback' } }"
          class="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-300 hover:text-white sm:block"
        >
          {{ t('site-header__nav-link--contact') }}
        </router-link>
        <router-link
          v-if="authStore.isAuthenticated"
          :to="authStore.homeRoute"
          class="rounded-lg px-3 py-2 text-sm font-medium text-slate-300 hover:text-white"
        >
          {{ authStore.isStaff ? t('site-header__nav-link--dashboard') : t('site-header__nav-link--garage') }}
        </router-link>
        <router-link
          v-else
          :to="{ name: 'login' }"
          class="rounded-lg px-3 py-2 text-sm font-medium text-slate-300 hover:text-white"
        >
          {{ t('site-header__nav-link--sign-in') }}
        </router-link>
        <router-link
          :to="{ name: 'book' }"
          class="whitespace-nowrap rounded-lg bg-amber-400 px-3 py-2 sm:px-4 text-sm font-semibold text-slate-900 shadow-sm hover:bg-amber-300"
        >
          <span class="hidden sm:inline">{{ t('site-header__cta') }}</span>
          <span class="sm:hidden">{{ t('site-header__cta--short') }}</span>
        </router-link>
      </nav>
    </div>
  </header>
</template>
