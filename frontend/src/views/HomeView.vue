<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// Public: anonymous visitors only get here while the server's REQUIRE_LOGIN is off
// (the router sends them to /login otherwise). Signed-in users go to the dashboard.
const router = useRouter()
const authStore = useAuthStore()

onMounted(() => {
  if (authStore.isAuthenticated) router.replace('/dashboard')
})
</script>

<template>
  <div v-if="!authStore.isAuthenticated" class="mx-auto max-w-3xl px-4 py-24 text-center sm:px-6 lg:px-8">
    <h1 class="text-4xl font-bold tracking-tight text-slate-950 sm:text-5xl">Welcome</h1>
    <p class="mt-4 text-lg leading-8 text-slate-600">
      This page is public. Mark a route <code class="rounded bg-slate-100 px-1.5 py-0.5 text-base">meta: {{ '{' }} public: true {{ '}' }}</code>
      to let visitors read it without signing in.
    </p>
    <router-link
      :to="{ name: 'login' }"
      class="mt-8 inline-flex rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
    >
      Sign in
    </router-link>
  </div>
</template>
