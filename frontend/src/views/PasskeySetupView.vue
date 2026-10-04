<script setup lang="ts">
// Shown after a password sign-in on an account that requires a passkey but
// has none saved yet. Nothing else works until one is saved (the API enforces
// it). Saving swaps in a normal session.
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { createPasskey, isPasskeyCancelled } from '@/services/passkeys'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const name = ref('Bitwarden')
const saving = ref(false)
const errorMessage = ref('')

const redirect = computed(() => {
  const value = route.query.redirect
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : null
})

async function create() {
  saving.value = true
  errorMessage.value = ''
  try {
    const result = await createPasskey(name.value.trim())
    authStore.completePasskeyLogin(result)
    router.push(redirect.value ?? authStore.homeRoute)
  } catch (error) {
    errorMessage.value = isPasskeyCancelled(error) ? t('passkey-setup__error--cancelled') : t('passkey-setup__error--generic')
  } finally {
    saving.value = false
  }
}

function signOut() {
  authStore.logout()
  router.push({ name: 'login' })
}

const inputClass =
  'mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2.5 text-slate-900 shadow-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-400/40'
</script>

<template>
  <div class="passkey-setup flex flex-1 items-center justify-center px-4 py-12">
    <div class="w-full max-w-md rounded-3xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
      <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-100 text-amber-700">
        <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.03 5.91c-.47-.08-.97.02-1.3.36L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.59a1 1 0 01.29-.7l5.95-5.96c.34-.33.44-.83.36-1.3A6 6 0 1121.75 8.25z" />
        </svg>
      </div>
      <h1 class="mt-4 text-2xl font-bold text-slate-900">{{ t('passkey-setup__title') }}</h1>
      <p class="mt-2 text-sm text-slate-600">{{ t('passkey-setup__intro') }}</p>
      <ol class="mt-4 list-decimal space-y-1 pl-5 text-sm text-slate-700">
        <li>{{ t('passkey-setup__step--1') }}</li>
        <li>{{ t('passkey-setup__step--2') }}</li>
      </ol>

      <form class="mt-6 space-y-4" @submit.prevent="create">
        <div>
          <label for="passkey-name" class="block text-sm font-medium text-slate-700">{{ t('passkey-setup__name-label') }}</label>
          <input id="passkey-name" v-model="name" type="text" maxlength="60" :class="inputClass" />
          <p class="mt-1 text-xs text-slate-500">{{ t('passkey-setup__name-hint') }}</p>
        </div>
        <p v-if="errorMessage" class="rounded-lg bg-red-50 p-3 text-sm text-red-800" role="alert">{{ errorMessage }}</p>
        <button
          type="submit"
          :disabled="saving"
          class="w-full rounded-xl bg-slate-900 px-5 py-3 font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {{ saving ? t('passkey-setup__submit--waiting') : t('passkey-setup__submit') }}
        </button>
      </form>
      <button type="button" class="mt-4 w-full text-center text-sm font-medium text-slate-500 hover:text-slate-800" @click="signOut">
        {{ t('app-nav__menu-item--logout') }}
      </button>
    </div>
  </div>
</template>
