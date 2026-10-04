<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import QuoteBreakdown from '@/components/QuoteBreakdown.vue'
import InvoiceCard from '@/components/InvoiceCard.vue'
import MessageThread from '@/components/MessageThread.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { mergeMessages, useLiveUpdates } from '@/composables/useLiveUpdates'
import { fetchMyOrder, pollMyOrder, sendCustomerMessage } from '@/services/account'
import type { OrderDetail } from '@/types/account'
import type { Quote } from '@/types/intake'
import { formatDate, formatMoney } from '@/utils/format'

const { t } = useI18n()
const route = useRoute()
const order = ref<OrderDetail | null>(null)
const loadError = ref(false)

const quote = computed(() => (order.value && 'total' in order.value.quote ? (order.value.quote as Quote) : null))

async function send(body: string) {
  if (!order.value) return
  const message = await sendCustomerMessage(order.value.id, body)
  order.value.messages = mergeMessages(order.value.messages, [message])
}

// Replies, status changes and the invoice show up without a reload.
const live = useLiveUpdates({
  poll: (afterId) => pollMyOrder(order.value!.id, afterId),
  messages: () => order.value?.messages,
  onMessages: (messages) => {
    if (order.value) order.value.messages = mergeMessages(order.value.messages, messages)
  },
  onChanged: async () => {
    const fresh = await fetchMyOrder(route.params.id as string)
    order.value = { ...fresh, messages: mergeMessages(order.value?.messages ?? [], fresh.messages) }
  }
})

onMounted(async () => {
  try {
    order.value = await fetchMyOrder(route.params.id as string)
    if (order.value.messaging_enabled) live.start(order.value.updated_at)
  } catch {
    loadError.value = true
  }
})
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-8 sm:px-6">
    <router-link to="/account" class="text-sm font-medium text-stone-500 hover:text-stone-800">← {{ t('account-order__back-link') }}</router-link>

    <p v-if="loadError" class="mt-6 rounded-xl bg-red-50 p-4 text-sm text-red-700">{{ t('account-order__not-found') }}</p>
    <div v-else-if="!order" class="mt-6 h-64 animate-pulse rounded-2xl bg-stone-200/60" />

    <template v-else>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <h1 class="text-2xl font-bold text-stone-900">{{ t(`account-order__title--${order.request_type}`, { id: order.id }) }}</h1>
        <StatusBadge :status="order.status" />
      </div>
      <p class="mt-1 text-stone-600">{{ t('account-order__when--sent', { date: formatDate(order.created_at) }) }}</p>

      <div class="mt-6 grid gap-6 md:grid-cols-[1fr_18rem]">
        <div class="space-y-6">
          <section v-if="order.invoice" class="account-invoice rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200">
            <h2 class="font-semibold text-stone-900">{{ t('account-order__invoice-title') }}</h2>
            <InvoiceCard class="mt-2" :invoice="order.invoice" />
          </section>

          <section v-if="order.messaging_enabled" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200">
            <h2 class="font-semibold text-stone-900">{{ t('account-order__messages-title') }}</h2>
            <p class="mt-1 text-sm text-stone-500">{{ t('account-order__messages-intro') }}</p>
            <div class="mt-4">
              <MessageThread :messages="order.messages" viewer="customer" :send="send" :placeholder="t('account-order__messages-placeholder')" />
            </div>
          </section>

          <section v-if="order.items.length || order.notes || order.placement_notes" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200">
            <h2 class="font-semibold text-stone-900">{{ t('account-order__items-title') }}</h2>
            <ul v-if="order.items.length" class="mt-3 flex flex-wrap gap-2">
              <li v-for="item in order.items" :key="item.key" class="rounded-full bg-stone-100 px-3 py-1 text-sm text-stone-700">
                {{ item.name }} · {{ item.quantity }} {{ t('order-products__unit') }}
              </li>
            </ul>
            <p v-if="order.placement_notes" class="mt-4 whitespace-pre-wrap text-sm text-stone-700">
              <span class="font-medium">{{ t('account-order__placement-label') }}</span> {{ order.placement_notes }}
            </p>
            <p v-if="order.notes" class="mt-4 whitespace-pre-wrap text-sm text-stone-700">
              <span class="font-medium">{{ t('account-order__notes-label') }}</span> {{ order.notes }}
            </p>
          </section>
        </div>

        <aside class="space-y-6">
          <section class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200">
            <h2 class="font-semibold text-stone-900">{{ t('account-order__delivery-title') }}</h2>
            <p v-if="order.delivered_on" class="mt-2 text-lg font-semibold text-emerald-700">{{ t('account-order__when--delivered', { date: formatDate(order.delivered_on) }) }}</p>
            <p v-else-if="order.scheduled_date" class="mt-2 text-lg font-semibold text-stone-900">
              {{ formatDate(order.scheduled_date) }}
              <span v-if="order.delivery_window !== 'any'" class="block text-sm font-normal text-stone-600">{{ t(`order-date__window--${order.delivery_window}`) }}</span>
            </p>
            <p v-else-if="order.preferred_date" class="mt-2 text-sm text-stone-600">{{ t('account-order__requested', { date: formatDate(order.preferred_date) }) }}</p>
            <p v-else class="mt-2 text-sm text-stone-600">{{ t('account-order__not-scheduled') }}</p>
            <p v-if="order.delivery_address" class="mt-2 text-sm text-stone-500">{{ order.delivery_address }} {{ order.zip_code }}</p>
          </section>

          <section v-if="!order.invoice && (quote || order.final_total)" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200">
            <h2 class="font-semibold text-stone-900">{{ order.final_total ? t('account-order__total-title--final') : t('account-order__total-title') }}</h2>
            <p v-if="order.final_total" class="mt-2 text-2xl font-bold text-stone-900">{{ formatMoney(order.final_total) }}</p>
            <QuoteBreakdown v-if="quote" class="mt-3" :quote="quote" :total-label="order.final_total ? t('quote-breakdown__total--original') : undefined" />
          </section>
        </aside>
      </div>
    </template>
  </div>
</template>
