<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { claimRequest } from '@/services/garage'

const route = useRoute()
const router = useRouter()
const failed = ref(false)

onMounted(async () => {
  try {
    const { id } = await claimRequest(route.params.token as string)
    router.replace({ name: 'account-request', params: { id } })
  } catch {
    failed.value = true
  }
})
</script>

<template>
  <div class="mx-auto max-w-md px-4 py-16 text-center">
    <template v-if="failed">
      <h1 class="text-xl font-bold text-slate-900">That link didn't work</h1>
      <p class="mt-2 text-slate-600">It may have already been used. If you saved this request before, it's in your garage.</p>
      <router-link to="/account" class="mt-6 inline-block rounded-xl bg-slate-900 px-5 py-2.5 font-semibold text-white">Go to my garage</router-link>
    </template>
    <p v-else class="text-slate-500">Adding this request to your garage…</p>
  </div>
</template>
