<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { claimOrder } from '@/services/account'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const failed = ref(false)

onMounted(async () => {
  try {
    const { id } = await claimOrder(route.params.token as string)
    router.replace({ name: 'account-order', params: { id } })
  } catch {
    failed.value = true
  }
})
</script>

<template>
  <div class="mx-auto max-w-md px-4 py-16 text-center">
    <template v-if="failed">
      <h1 class="text-xl font-bold text-stone-900">{{ t('claim-page__error-title') }}</h1>
      <p class="mt-2 text-stone-600">{{ t('claim-page__error-body') }}</p>
      <router-link to="/account" class="mt-6 inline-block rounded-xl bg-stone-900 px-5 py-2.5 font-semibold text-white">{{ t('claim-page__orders-link') }}</router-link>
    </template>
    <p v-else class="text-stone-500">{{ t('claim-page__pending') }}</p>
  </div>
</template>
