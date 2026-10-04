<script setup lang="ts">
// Step 2 of a password reset: the page the emailed link opens.
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import axios from 'axios'
import { confirmPasswordReset } from '@/services/auth'

const { t } = useI18n()
const route = useRoute()

const password = ref('')
const confirm = ref('')
const saving = ref(false)
const done = ref(false)
const linkInvalid = ref(false)
const passwordError = ref('')
const errorMessage = ref('')

const mismatch = computed(() => !!confirm.value && password.value !== confirm.value)

async function submit() {
  passwordError.value = ''
  errorMessage.value = ''
  if (password.value !== confirm.value) {
    passwordError.value = t('auth-reset__error--mismatch')
    return
  }
  saving.value = true
  try {
    await confirmPasswordReset(String(route.params.uid), String(route.params.token), password.value)
    done.value = true
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 400) {
      const data = error.response.data as { token?: string[]; password?: string[] }
      if (data.token) linkInvalid.value = true
      // Password rules come back already translated by the server.
      else passwordError.value = data.password?.join(' ') ?? t('auth-reset__error--generic')
    } else {
      errorMessage.value =
        axios.isAxiosError(error) && error.response?.status === 429
          ? t('auth-forgot__error--rate-limited')
          : t('auth-reset__error--generic')
    }
  } finally {
    saving.value = false
  }
}

const inputClass =
  'mt-1 block w-full rounded-lg border border-stone-300 px-3 py-2.5 text-stone-900 shadow-sm focus:border-lime-500 focus:outline-none focus:ring-2 focus:ring-lime-400/40'
</script>

<template>
  <div class="auth-reset flex flex-1 items-center justify-center px-4 py-12">
    <div class="w-full max-w-md rounded-3xl bg-white p-8 shadow-sm ring-1 ring-stone-200">
      <h1 class="text-2xl font-bold text-stone-900">{{ t('auth-reset__title') }}</h1>

      <template v-if="done">
        <p class="mt-4 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900 ring-1 ring-emerald-200" role="status">
          {{ t('auth-reset__done') }}
        </p>
        <router-link
          :to="{ name: 'login' }"
          class="mt-6 block w-full rounded-xl bg-stone-900 px-5 py-3 text-center font-semibold text-white hover:bg-stone-800"
        >
          {{ t('auth-reset__sign-in') }}
        </router-link>
      </template>

      <template v-else-if="linkInvalid">
        <p class="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-800" role="alert">{{ t('auth-reset__invalid') }}</p>
        <router-link
          :to="{ name: 'forgot-password' }"
          class="mt-6 block w-full rounded-xl bg-stone-900 px-5 py-3 text-center font-semibold text-white hover:bg-stone-800"
        >
          {{ t('auth-reset__new-link') }}
        </router-link>
      </template>

      <form v-else class="mt-6 space-y-4" @submit.prevent="submit">
        <div>
          <label for="new-password" class="block text-sm font-medium text-stone-700">{{ t('auth-reset__password-label') }}</label>
          <input id="new-password" v-model="password" type="password" autocomplete="new-password" required minlength="8" :class="inputClass" />
          <p class="mt-1 text-xs text-stone-500">{{ t('auth-register__password-hint') }}</p>
        </div>
        <div>
          <label for="confirm-password" class="block text-sm font-medium text-stone-700">{{ t('auth-reset__confirm-label') }}</label>
          <input id="confirm-password" v-model="confirm" type="password" autocomplete="new-password" required :class="[inputClass, mismatch && 'border-red-400']" />
        </div>
        <p v-if="passwordError || mismatch" class="text-sm text-red-600">{{ passwordError || t('auth-reset__error--mismatch') }}</p>
        <p v-if="errorMessage" class="rounded-lg bg-red-50 p-3 text-sm text-red-800">{{ errorMessage }}</p>
        <button
          type="submit"
          :disabled="saving || mismatch"
          class="w-full rounded-xl bg-stone-900 px-5 py-3 font-semibold text-white hover:bg-stone-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {{ saving ? t('auth-reset__submit--loading') : t('auth-reset__submit') }}
        </button>
      </form>
    </div>
  </div>
</template>
