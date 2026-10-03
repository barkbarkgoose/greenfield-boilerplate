<script setup lang="ts">
// Step 1 of a password reset: ask for the email. The answer is the same
// whether or not an account exists, so this can't be used to probe emails.
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import axios from 'axios'
import { requestPasswordReset } from '@/services/auth'

const { t } = useI18n()
const route = useRoute()

const email = ref(typeof route.query.email === 'string' ? route.query.email : '')
const sending = ref(false)
const sentTo = ref('')
const errorMessage = ref('')

async function submit() {
  sending.value = true
  errorMessage.value = ''
  try {
    await requestPasswordReset(email.value.trim())
    sentTo.value = email.value.trim()
  } catch (error) {
    errorMessage.value =
      axios.isAxiosError(error) && error.response?.status === 429
        ? t('auth-forgot__error--rate-limited')
        : t('auth-forgot__error--generic')
  } finally {
    sending.value = false
  }
}

const inputClass =
  'mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2.5 text-slate-900 shadow-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-400/40'
</script>

<template>
  <div class="auth-forgot flex flex-1 items-center justify-center px-4 py-12">
    <div class="w-full max-w-md rounded-3xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
      <h1 class="text-2xl font-bold text-slate-900">{{ t('auth-forgot__title') }}</h1>

      <template v-if="sentTo">
        <p class="mt-4 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900 ring-1 ring-emerald-200" role="status">
          {{ t('auth-forgot__sent', { email: sentTo }) }}
        </p>
        <p class="mt-4 text-sm text-slate-600">{{ t('auth-forgot__sent-hint') }}</p>
        <button type="button" class="mt-4 text-sm font-semibold text-amber-700 hover:text-amber-600" @click="sentTo = ''">
          {{ t('auth-forgot__try-again') }}
        </button>
      </template>

      <template v-else>
        <p class="mt-2 text-sm text-slate-600">{{ t('auth-forgot__intro') }}</p>
        <form class="mt-6 space-y-4" @submit.prevent="submit">
          <div>
            <label for="email-address" class="block text-sm font-medium text-slate-700">{{ t('auth-login__email-label') }}</label>
            <input id="email-address" v-model="email" type="email" autocomplete="email" required :class="inputClass" />
          </div>
          <p v-if="errorMessage" class="rounded-lg bg-red-50 p-3 text-sm text-red-800">{{ errorMessage }}</p>
          <button
            type="submit"
            :disabled="sending"
            class="w-full rounded-xl bg-slate-900 px-5 py-3 font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {{ sending ? t('auth-forgot__submit--loading') : t('auth-forgot__submit') }}
          </button>
        </form>
      </template>

      <p class="mt-6 text-sm text-slate-600">
        <router-link :to="{ name: 'login' }" class="font-semibold text-amber-700 hover:text-amber-600">← {{ t('auth-forgot__back-link') }}</router-link>
      </p>
    </div>
  </div>
</template>
