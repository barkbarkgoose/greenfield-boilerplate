<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const email = ref('')
const password = ref('')
const isLoading = ref(false)
const errorMessage = ref('')

// Only follow in-app redirects (e.g. a claim link), never absolute URLs.
const redirect = computed(() => {
  const value = route.query.redirect
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : null
})
const isClaim = computed(() => redirect.value?.startsWith('/claim/') ?? false)

async function handleSubmit() {
  isLoading.value = true
  errorMessage.value = ''

  try {
    await authStore.login({ email: email.value, password: password.value })
    router.push(redirect.value ?? authStore.homeRoute)
  } catch (error: unknown) {
    if (error && typeof error === 'object' && 'response' in error) {
      // The API's 401 text is English-only; show our own translated message.
      const err = error as { response?: { status?: number; data?: { detail?: string } } }
      errorMessage.value =
        err.response?.status === 401
          ? t('auth-login__error--credentials')
          : err.response?.data?.detail || t('auth-login__error--generic')
    } else {
      errorMessage.value = t('auth-login__error--generic')
    }
  } finally {
    isLoading.value = false
  }
}

const inputClass =
  'mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2.5 text-slate-900 shadow-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-400/40'
</script>

<template>
  <div class="flex flex-1 flex-col">
    <div class="flex flex-1 items-center justify-center px-4 py-12">
      <div class="w-full max-w-md rounded-3xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
        <h1 class="text-2xl font-bold text-slate-900">{{ t('auth-login__title') }}</h1>
        <p class="mt-2 text-sm text-slate-600">
          {{ isClaim ? t('auth-login__intro--claim') : t('auth-login__intro') }}
          {{ t('auth-login__register-prompt') }}
          <router-link :to="{ name: 'register', query: route.query }" class="font-semibold text-amber-700 hover:text-amber-600">
            {{ t('auth-login__register-link') }}
          </router-link>
        </p>

        <form class="mt-6 space-y-4" @submit.prevent="handleSubmit">
          <div>
            <label for="email-address" class="block text-sm font-medium text-slate-700">{{ t('auth-login__email-label') }}</label>
            <input id="email-address" v-model="email" type="email" autocomplete="email" required :class="inputClass" />
          </div>
          <div>
            <label for="password" class="block text-sm font-medium text-slate-700">{{ t('auth-login__password-label') }}</label>
            <input id="password" v-model="password" type="password" autocomplete="current-password" required :class="inputClass" />
          </div>

          <p v-if="errorMessage" class="rounded-lg bg-red-50 p-3 text-sm text-red-800">{{ errorMessage }}</p>

          <button
            type="submit"
            :disabled="isLoading"
            class="w-full rounded-xl bg-slate-900 px-5 py-3 font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {{ isLoading ? t('auth-login__submit--loading') : t('auth-login__submit') }}
          </button>
        </form>
      </div>
    </div>
  </div>
</template>
