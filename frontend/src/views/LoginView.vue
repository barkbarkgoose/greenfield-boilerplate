<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import PublicHeader from '@/components/PublicHeader.vue'

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
      const err = error as { response?: { data?: { detail?: string } } }
      errorMessage.value = err.response?.data?.detail || 'Invalid email or password'
    } else {
      errorMessage.value = 'Login failed. Please try again.'
    }
  } finally {
    isLoading.value = false
  }
}

const inputClass =
  'mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2.5 text-slate-900 shadow-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-400/40'
</script>

<template>
  <div class="flex min-h-screen flex-col bg-slate-50">
    <PublicHeader />
    <div class="flex flex-1 items-center justify-center px-4 py-12">
      <div class="w-full max-w-md rounded-3xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
        <h1 class="text-2xl font-bold text-slate-900">Sign in</h1>
        <p class="mt-2 text-sm text-slate-600">
          <template v-if="isClaim">Sign in to save your request to your garage.</template>
          <template v-else>See your vehicles, repair history and messages.</template>
          New here?
          <router-link :to="{ name: 'register', query: route.query }" class="font-semibold text-amber-700 hover:text-amber-600">
            Create an account
          </router-link>
        </p>

        <form class="mt-6 space-y-4" @submit.prevent="handleSubmit">
          <div>
            <label for="email-address" class="block text-sm font-medium text-slate-700">Email</label>
            <input id="email-address" v-model="email" type="email" autocomplete="email" required :class="inputClass" />
          </div>
          <div>
            <label for="password" class="block text-sm font-medium text-slate-700">Password</label>
            <input id="password" v-model="password" type="password" autocomplete="current-password" required :class="inputClass" />
          </div>

          <p v-if="errorMessage" class="rounded-lg bg-red-50 p-3 text-sm text-red-800">{{ errorMessage }}</p>

          <button
            type="submit"
            :disabled="isLoading"
            class="w-full rounded-xl bg-slate-900 px-5 py-3 font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {{ isLoading ? 'Signing in…' : 'Sign in' }}
          </button>
        </form>
      </div>
    </div>
  </div>
</template>
