<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import EstimateBreakdown from '@/components/EstimateBreakdown.vue'
import InvoiceCard from '@/components/InvoiceCard.vue'
import MessageThread from '@/components/MessageThread.vue'
import PartsEstimateCard from '@/components/PartsEstimateCard.vue'
import { usePartsEstimate } from '@/composables/usePartsEstimate'
import { mergeMessages, useLiveUpdates } from '@/composables/useLiveUpdates'
import StatusBadge from '@/components/StatusBadge.vue'
import { fetchMyRequest, pollMyRequest, sendCustomerMessage } from '@/services/garage'
import type { RequestDetail } from '@/types/garage'
import type { Estimate } from '@/types/intake'
import { formatDate, formatDateTime, formatMoney } from '@/utils/intake'
import { intlLocale } from '@/i18n'

const { t } = useI18n()
const route = useRoute()
const request = ref<RequestDetail | null>(null)
const loadError = ref(false)

const estimate = computed(() =>
  request.value && 'total' in request.value.estimate ? (request.value.estimate as Estimate) : null
)
const parts = usePartsEstimate(async () => (await fetchMyRequest(route.params.id as string)).parts_estimate)

const vehicleLabel = computed(() => request.value?.vehicle?.label || request.value?.vehicle_label || '')

async function send(body: string) {
  if (!request.value) return
  const message = await sendCustomerMessage(request.value.id, body)
  request.value.messages = mergeMessages(request.value.messages, [message])
}

// Replies, status changes and the invoice show up without a reload.
const live = useLiveUpdates({
  poll: (afterId) => pollMyRequest(request.value!.id, afterId),
  messages: () => request.value?.messages,
  onMessages: (messages) => {
    if (request.value) request.value.messages = mergeMessages(request.value.messages, messages)
  },
  onChanged: async () => {
    const fresh = await fetchMyRequest(route.params.id as string)
    request.value = { ...fresh, messages: mergeMessages(request.value?.messages ?? [], fresh.messages) }
    parts.start(fresh.parts_estimate)
  }
})

onMounted(async () => {
  try {
    request.value = await fetchMyRequest(route.params.id as string)
    parts.start(request.value.parts_estimate)
    if (request.value.messaging_enabled) live.start(request.value.updated_at)
  } catch {
    loadError.value = true
  }
})
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-8 sm:px-6">
    <router-link to="/account" class="text-sm font-medium text-slate-500 hover:text-slate-800">← {{ t('garage-request__back-link') }}</router-link>

    <p v-if="loadError" class="mt-6 rounded-xl bg-red-50 p-4 text-sm text-red-700">
      {{ t('garage-request__not-found') }}
    </p>
    <div v-else-if="!request" class="mt-6 h-64 animate-pulse rounded-2xl bg-slate-200/60" />

    <template v-else>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <h1 class="text-2xl font-bold text-slate-900">
          {{ t(request.request_type === 'callback' ? 'garage-request__title--callback' : 'garage-request__title--booking', { id: request.id }) }}
        </h1>
        <StatusBadge :status="request.status" />
      </div>
      <p class="mt-1 text-slate-600">
        <template v-if="vehicleLabel">{{ vehicleLabel }} · </template>{{ t('garage-request__sent', { date: formatDate(request.created_at) }) }}
      </p>

      <div class="mt-6 grid gap-6 md:grid-cols-[1fr_18rem]">
        <div class="space-y-6">
          <section v-if="request.invoice" class="garage-invoice rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">{{ t('garage-request__invoice-title') }}</h2>
            <InvoiceCard class="mt-2" :invoice="request.invoice" />
          </section>

          <section v-if="request.messaging_enabled" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">{{ t('garage-request__messages-title') }}</h2>
            <p class="mt-1 text-sm text-slate-500">{{ t('garage-request__messages-intro') }}</p>
            <div class="mt-4">
              <MessageThread
                :messages="request.messages"
                viewer="customer"
                :send="send"
                :placeholder="t('garage-request__messages-placeholder')"
              />
            </div>
          </section>

          <section v-if="request.services.length || request.other_description || request.notes" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">{{ t('garage-request__work-title') }}</h2>
            <ul v-if="request.services.length" class="mt-3 flex flex-wrap gap-2">
              <li v-for="s in request.services" :key="s.key" class="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-700">
                {{ s.name }}<template v-if="s.quantity > 1"> ×{{ s.quantity }}</template>
              </li>
            </ul>
            <p v-if="request.other_description" class="mt-4 whitespace-pre-wrap text-sm text-slate-700">
              <span class="font-medium">{{ t('garage-request__other-label') }}</span> {{ request.other_description }}
            </p>
            <p v-if="request.notes" class="mt-4 whitespace-pre-wrap text-sm text-slate-700">
              <span class="font-medium">{{ t('garage-request__notes-label') }}</span> {{ request.notes }}
            </p>
          </section>
        </div>

        <aside class="space-y-6">
          <section class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">{{ t('garage-request__appointment-title') }}</h2>
            <p v-if="request.scheduled_for" class="mt-2 text-lg font-semibold text-slate-900">{{ formatDateTime(request.scheduled_for) }}</p>
            <p v-else-if="request.preferred_date" class="mt-2 text-sm text-slate-600">
              {{ t('garage-request__appointment-requested', { date: formatDate(request.preferred_date) }) }}
            </p>
            <p v-else class="mt-2 text-sm text-slate-600">{{ t('garage-request__appointment-none') }}</p>
            <p v-if="request.service_address" class="mt-2 text-sm text-slate-500">{{ request.service_address }}</p>
            <p v-if="request.completed_on" class="mt-3 text-sm text-emerald-700">
              {{ t('garage-request__completed', { date: formatDate(request.completed_on) }) }}<template v-if="request.odometer"> · {{ t('garage-history__odometer', { miles: request.odometer.toLocaleString(intlLocale()) }) }}</template>
            </p>
          </section>

          <section v-if="!request.invoice && (estimate || request.final_total)" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">{{ request.final_total ? t('garage-request__total-title--final') : t('garage-request__total-title') }}</h2>
            <p v-if="request.final_total" class="mt-2 text-2xl font-bold text-slate-900">{{ formatMoney(request.final_total) }}</p>
            <EstimateBreakdown
              v-if="estimate"
              class="mt-3"
              :estimate="estimate"
              :total-label="request.final_total ? t('estimate-breakdown__total--original') : t('estimate-breakdown__total')"
            />
            <p v-if="!request.final_total && !parts.estimate.value" class="mt-2 text-xs text-slate-500">{{ t('garage-request__labor-note') }}</p>
          </section>

          <section v-if="parts.estimate.value && !request.final_total && !request.invoice" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="mb-3 font-semibold text-slate-900">{{ t('garage-request__parts-title') }}</h2>
            <PartsEstimateCard
              :estimate="parts.estimate.value"
              :labor-total="estimate?.total ?? null"
              :vehicle-label="vehicleLabel"
            />
          </section>
        </aside>
      </div>
    </template>
  </div>
</template>
