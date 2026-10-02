<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import EstimateBreakdown from '@/components/EstimateBreakdown.vue'
import MessageThread from '@/components/MessageThread.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { fetchMyRequest, sendCustomerMessage } from '@/services/garage'
import type { RequestDetail } from '@/types/garage'
import type { Estimate } from '@/types/intake'
import { formatDate, formatDateTime, formatMoney } from '@/utils/intake'

const route = useRoute()
const request = ref<RequestDetail | null>(null)
const loadError = ref(false)

const estimate = computed(() =>
  request.value && 'total' in request.value.estimate ? (request.value.estimate as Estimate) : null
)
const vehicleLabel = computed(() => request.value?.vehicle?.label || request.value?.vehicle_label || '')

async function send(body: string) {
  if (!request.value) return
  const message = await sendCustomerMessage(request.value.id, body)
  request.value.messages.push(message)
}

onMounted(async () => {
  try {
    request.value = await fetchMyRequest(route.params.id as string)
  } catch {
    loadError.value = true
  }
})
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-8 sm:px-6">
    <router-link to="/account" class="text-sm font-medium text-slate-500 hover:text-slate-800">← My garage</router-link>

    <p v-if="loadError" class="mt-6 rounded-xl bg-red-50 p-4 text-sm text-red-700">
      This request couldn't be found.
    </p>
    <div v-else-if="!request" class="mt-6 h-64 animate-pulse rounded-2xl bg-slate-200/60" />

    <template v-else>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <h1 class="text-2xl font-bold text-slate-900">
          {{ request.request_type === 'callback' ? 'Contact request' : 'Service request' }} #{{ request.id }}
        </h1>
        <StatusBadge :status="request.status" />
      </div>
      <p class="mt-1 text-slate-600">
        <template v-if="vehicleLabel">{{ vehicleLabel }} · </template>Sent {{ formatDate(request.created_at) }}
      </p>

      <div class="mt-6 grid gap-6 md:grid-cols-[1fr_18rem]">
        <div class="space-y-6">
          <section class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">Questions &amp; notes</h2>
            <p class="mt-1 text-sm text-slate-500">Ask anything about this job. I'll get an email and reply here.</p>
            <div class="mt-4">
              <MessageThread
                :messages="request.messages"
                viewer="customer"
                :send="send"
                placeholder="e.g. Could we move it to the afternoon? Is synthetic oil OK?"
              />
            </div>
          </section>

          <section v-if="request.services.length || request.other_description || request.notes" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">What you asked for</h2>
            <ul v-if="request.services.length" class="mt-3 flex flex-wrap gap-2">
              <li v-for="s in request.services" :key="s.key" class="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-700">
                {{ s.name }}<template v-if="s.quantity > 1"> ×{{ s.quantity }}</template>
              </li>
            </ul>
            <p v-if="request.other_description" class="mt-4 whitespace-pre-wrap text-sm text-slate-700">
              <span class="font-medium">Other work:</span> {{ request.other_description }}
            </p>
            <p v-if="request.notes" class="mt-4 whitespace-pre-wrap text-sm text-slate-700">
              <span class="font-medium">Notes:</span> {{ request.notes }}
            </p>
          </section>
        </div>

        <aside class="space-y-6">
          <section class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">Appointment</h2>
            <p v-if="request.scheduled_for" class="mt-2 text-lg font-semibold text-slate-900">{{ formatDateTime(request.scheduled_for) }}</p>
            <p v-else-if="request.preferred_date" class="mt-2 text-sm text-slate-600">
              Requested around {{ formatDate(request.preferred_date) }}. I'll confirm a time with you.
            </p>
            <p v-else class="mt-2 text-sm text-slate-600">Not scheduled yet.</p>
            <p v-if="request.service_address" class="mt-2 text-sm text-slate-500">{{ request.service_address }}</p>
            <p v-if="request.completed_on" class="mt-3 text-sm text-emerald-700">
              Completed {{ formatDate(request.completed_on) }}<template v-if="request.odometer"> at {{ request.odometer.toLocaleString() }} mi</template>
            </p>
          </section>

          <section v-if="estimate || request.final_total" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">{{ request.final_total ? 'Total' : 'Estimate' }}</h2>
            <p v-if="request.final_total" class="mt-2 text-2xl font-bold text-slate-900">{{ formatMoney(request.final_total) }}</p>
            <EstimateBreakdown
              v-if="estimate"
              class="mt-3"
              :estimate="estimate"
              :total-label="request.final_total ? 'Original estimate' : 'Estimated total'"
            />
            <p v-if="!request.final_total" class="mt-2 text-xs text-slate-500">Labor only; parts quoted separately.</p>
          </section>
        </aside>
      </div>
    </template>
  </div>
</template>
