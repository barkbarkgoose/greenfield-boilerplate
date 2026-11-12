<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { passkeyErrorMessage, passkeysSupported } from '@/services/passkeys'
import { useAuthStore } from '@/stores/auth'

// After sign-in: staff without a passkey must add one (the only way out is logging out);
// other users are offered one once per password sign-in.
const router = useRouter()
const authStore = useAuthStore()

const prompt = computed(() => authStore.passkeyPrompt)
const required = computed(() => prompt.value === 'required')
const canUsePasskey = passkeysSupported()
const isSaving = ref(false)
const errorMessage = ref('')

async function add() {
  isSaving.value = true
  errorMessage.value = ''
  try {
    await authStore.addPasskey()
  } catch (error: unknown) {
    errorMessage.value = passkeyErrorMessage(error) ?? ''
  } finally {
    isSaving.value = false
  }
}

async function dismiss(forever: boolean) {
  errorMessage.value = ''
  try {
    await authStore.dismissPasskeyOffer(forever)
  } catch {
    // the offer is closed already; it may come back after the next sign-in
  }
}

async function logOut() {
  await authStore.logout()
  router.push('/login')
}
</script>

<template>
  <div
    v-if="prompt"
    class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="passkey-prompt-title"
  >
    <div class="w-full max-w-md rounded-3xl bg-white p-6 shadow-xl sm:p-8">
      <span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
        </svg>
      </span>

      <template v-if="required">
        <h2 id="passkey-prompt-title" class="mt-5 text-xl font-semibold text-slate-950">Add a passkey to your admin account</h2>
        <p class="mt-2 text-sm leading-6 text-slate-600">
          Admin accounts sign in with a passkey: your fingerprint, face or device PIN instead of a password.
          After this, your password alone won't sign you in.
        </p>
        <p v-if="!canUsePasskey" class="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
          This browser can't create passkeys here. Open the app over https in a current browser to continue.
        </p>
      </template>
      <template v-else>
        <h2 id="passkey-prompt-title" class="mt-5 text-xl font-semibold text-slate-950">Sign in faster with a passkey</h2>
        <p class="mt-2 text-sm leading-6 text-slate-600">
          Use your fingerprint, face or screen lock instead of typing your password. You can manage passkeys in
          Profile &amp; settings.
        </p>
      </template>

      <p v-if="errorMessage" class="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-800">{{ errorMessage }}</p>

      <div class="mt-6 flex flex-col gap-2">
        <button
          v-if="canUsePasskey"
          type="button"
          :disabled="isSaving"
          class="rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
          @click="add"
        >
          {{ isSaving ? 'Waiting for your passkey...' : 'Add a passkey' }}
        </button>
        <template v-if="required">
          <button type="button" class="rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-100" @click="logOut">
            Log out
          </button>
        </template>
        <div v-else class="flex gap-2">
          <button type="button" class="flex-1 rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-100" @click="dismiss(false)">
            Not now
          </button>
          <button type="button" class="flex-1 rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-100" @click="dismiss(true)">
            Don't ask again
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
