<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isServerPage } from '@/router'
import { passkeyErrorMessage, passkeysSupported } from '@/services/passkeys'
import { useAuthStore } from '@/stores/auth'
import { firstError } from '@/utils/apiErrors'
import { safeRedirect } from '@/utils/redirect'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

onMounted(() => authStore.loadAuthConfig())

const email = ref('')
const password = ref('')
const isLoading = ref(false)
const isPasskeyLoading = ref(false)
const errorMessage = ref('')
const canUsePasskey = passkeysSupported()
// on the way to the Django admin, which only a passkey sign-in opens
const toAdmin = computed(() => isServerPage(route.query.redirect))

function goNext(method: 'pwd' | 'passkey') {
  const target = safeRedirect(route.query.redirect)
  if (target && isServerPage(target)) {
    // Only a staff passkey sign-in opens an admin session; anyone else would be sent
    // straight back here.
    if (method === 'passkey' && authStore.user?.is_staff) {
      window.location.assign(target)
      return
    }
    router.push('/dashboard')
    return
  }
  router.push(target ?? '/dashboard')
}

async function handleSubmit() {
  isLoading.value = true
  errorMessage.value = ''
  
  try {
    await authStore.login({ email: email.value, password: password.value })
    goNext('pwd')
  } catch (error: unknown) {
    if (error && typeof error === 'object' && 'response' in error) {
      const err = error as { response?: { data?: unknown } }
      errorMessage.value = firstError(err.response?.data) || 'Invalid email or password'
    } else {
      errorMessage.value = 'Login failed. Please try again.'
    }
  } finally {
    isLoading.value = false
  }
}

async function handlePasskey() {
  isPasskeyLoading.value = true
  errorMessage.value = ''
  try {
    await authStore.loginWithPasskey()
    goNext('passkey')
  } catch (error: unknown) {
    errorMessage.value = passkeyErrorMessage(error) ?? ''
  } finally {
    isPasskeyLoading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8">
      <div>
        <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">
          Sign in to your account
        </h2>
        <p v-if="toAdmin" class="mt-2 text-center text-sm text-gray-600">
          Sign in with your passkey to continue to the admin.
        </p>
        <p v-if="authStore.allowRegistration" class="mt-2 text-center text-sm text-gray-600">
          Or
          <router-link to="/register" class="font-medium text-blue-600 hover:text-blue-500">
            create a new account
          </router-link>
        </p>
      </div>

      <form class="mt-8 space-y-6" @submit.prevent="handleSubmit">
        <div class="rounded-md shadow-sm -space-y-px">
          <div>
            <label for="email-address" class="sr-only">Email address</label>
            <input
              id="email-address"
              v-model="email"
              type="email"
              required
              class="appearance-none rounded-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-t-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 focus:z-10 sm:text-sm"
              placeholder="Email address"
            />
          </div>
          <div>
            <label for="password" class="sr-only">Password</label>
            <input
              id="password"
              v-model="password"
              type="password"
              required
              class="appearance-none rounded-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-b-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 focus:z-10 sm:text-sm"
              placeholder="Password"
            />
          </div>
        </div>

        <div v-if="errorMessage" class="rounded-md bg-red-50 p-4">
          <p class="text-sm text-red-800">{{ errorMessage }}</p>
        </div>

        <div>
          <button
            type="submit"
            :disabled="isLoading"
            class="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span v-if="isLoading" class="absolute left-0 inset-y-0 flex items-center pl-3">
              <svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            </span>
            {{ isLoading ? 'Signing in...' : 'Sign in' }}
          </button>
        </div>
      </form>

      <div v-if="canUsePasskey" class="space-y-6">
        <div class="flex items-center gap-3 text-xs uppercase tracking-wider text-gray-400">
          <span class="h-px flex-1 bg-gray-200"></span>
          or
          <span class="h-px flex-1 bg-gray-200"></span>
        </div>
        <button
          type="button"
          :disabled="isPasskeyLoading"
          class="w-full flex items-center justify-center gap-2 py-2 px-4 border border-gray-300 text-sm font-medium rounded-md text-gray-800 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          @click="handlePasskey"
        >
          <svg class="h-5 w-5 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
          </svg>
          {{ isPasskeyLoading ? 'Waiting for your passkey...' : 'Sign in with a passkey' }}
        </button>
      </div>
    </div>
  </div>
</template>
