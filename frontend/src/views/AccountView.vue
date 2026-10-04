<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import StatusBadge from '@/components/StatusBadge.vue'
import { useAuthStore } from '@/stores/auth'
import { fetchMyOrders } from '@/services/account'
import type { OrderSummary } from '@/types/account'
import { formatDate, formatMoney, itemsLabel } from '@/utils/format'

const { t } = useI18n()
const authStore = useAuthStore()

const orders = ref<OrderSummary[]>([])
const loading = ref(true)
const loadError = ref(false)

const firstName = computed(() => authStore.user?.name?.split(' ')[0] || '')
const open = computed(() => orders.value.filter((o) => ['new', 'contacted', 'scheduled'].includes(o.status)))
const past = computed(() => orders.value.filter((o) => !['new', 'contacted', 'scheduled'].includes(o.status)))
const totalUnread = computed(() => orders.value.reduce((sum, o) => sum + o.unread_count, 0))

function when(o: OrderSummary): string {
  return o.delivered_on || o.scheduled_date || o.preferred_date || o.created_at.slice(0, 10)
}

function whenLabel(o: OrderSummary): string {
  if (o.delivered_on) return t('account-order__when--delivered', { date: formatDate(o.delivered_on) })
  if (o.scheduled_date) return t('account-order__when--scheduled', { date: formatDate(o.scheduled_date) })
  if (o.preferred_date) return t('account-order__when--requested', { date: formatDate(o.preferred_date) })
  return t('account-order__when--sent', { date: formatDate(o.created_at) })
}

const sections = computed(() => [
  { key: 'open', orders: open.value },
  { key: 'past', orders: past.value }
].filter((section) => section.orders.length > 0))

onMounted(async () => {
  try {
    orders.value = (await fetchMyOrders()).sort((a, b) => when(b).localeCompare(when(a)))
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-8 sm:px-6">
    <div class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-stone-900">
          {{ firstName ? t('account-overview__title', { name: firstName }) : t('account-overview__title--anonymous') }}
        </h1>
        <p class="mt-1 text-stone-600">
          {{ t('account-overview__intro') }}
          <span v-if="totalUnread" class="font-semibold text-lime-700">{{ t('account-overview__unread', totalUnread) }}</span>
        </p>
      </div>
      <router-link :to="{ name: 'order' }" class="rounded-xl bg-lime-500 px-5 py-2.5 text-center font-semibold text-stone-900 hover:bg-lime-400">
        {{ t('account-overview__cta') }}
      </router-link>
    </div>

    <div v-if="loading" class="mt-8 space-y-4">
      <div v-for="n in 2" :key="n" class="h-32 animate-pulse rounded-2xl bg-stone-200/60" />
    </div>
    <p v-else-if="loadError" class="mt-8 rounded-xl bg-red-50 p-4 text-sm text-red-700">{{ t('account-overview__load-error') }}</p>

    <div v-else-if="orders.length === 0" class="mt-8 rounded-3xl bg-white p-10 text-center shadow-sm ring-1 ring-stone-200">
      <p class="text-lg font-semibold text-stone-900">{{ t('account-empty__title') }}</p>
      <p class="mx-auto mt-2 max-w-md text-sm text-stone-600">{{ t('account-empty__body') }}</p>
      <router-link :to="{ name: 'order' }" class="mt-6 inline-block rounded-xl bg-stone-900 px-5 py-2.5 font-semibold text-white hover:bg-stone-800">
        {{ t('account-empty__cta') }}
      </router-link>
    </div>

    <section v-for="section in sections" v-else :key="section.key" class="mt-8">
      <h2 class="text-sm font-semibold uppercase tracking-wider text-stone-500">{{ t(`account-overview__section--${section.key}`) }}</h2>
      <ul class="mt-3 divide-y divide-stone-100 overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-stone-200">
        <li v-for="o in section.orders" :key="o.id" class="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:gap-4">
          <router-link :to="{ name: 'account-order', params: { id: o.id } }" class="min-w-0 flex-1 hover:opacity-80">
            <p class="truncate font-medium text-stone-900">
              {{ o.request_type === 'callback' && !o.items.length ? t('account-order__special-request') : itemsLabel(o.items, t('order-products__unit')) }}
            </p>
            <p class="mt-0.5 truncate text-xs text-stone-500">
              {{ whenLabel(o) }}<template v-if="o.delivery_address || o.city"> · {{ o.delivery_address || o.city }}</template>
              <template v-if="o.final_total"> · {{ t('account-order__paid', { amount: formatMoney(o.final_total) }) }}</template>
              <template v-else-if="o.estimated_total"> · {{ t('account-order__estimated', { amount: formatMoney(o.estimated_total) }) }}</template>
            </p>
          </router-link>
          <div class="flex items-center gap-2">
            <span v-if="o.unread_count" class="rounded-full bg-lime-500 px-2 py-0.5 text-xs font-bold text-stone-900">{{ t('account-order__unread-badge', { count: o.unread_count }) }}</span>
            <StatusBadge :status="o.status" />
            <router-link
              v-if="o.items.length && o.zip_code"
              :to="{ name: 'order', query: { from: o.id } }"
              class="rounded-lg px-2.5 py-1 text-xs font-semibold text-stone-700 ring-1 ring-stone-300 hover:bg-stone-50"
            >
              {{ t('account-order__reorder') }}
            </router-link>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
