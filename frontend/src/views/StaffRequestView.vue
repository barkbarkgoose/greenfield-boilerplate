<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import EstimateBreakdown from '@/components/EstimateBreakdown.vue'
import InvoiceEditor from '@/components/InvoiceEditor.vue'
import MessageThread from '@/components/MessageThread.vue'
import PartsEstimateCard from '@/components/PartsEstimateCard.vue'
import { usePartsEstimate } from '@/composables/usePartsEstimate'
import { mergeMessages, useLiveUpdates } from '@/composables/useLiveUpdates'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  fetchStaffRequest,
  pollStaffRequest,
  retryPartsEstimate,
  sendStaffMessage,
  updateStaffRequest
} from '@/services/garage'
import type { Invoice, RequestStatus, StaffRequestDetail } from '@/types/garage'
import { VEHICLE_TYPES } from '@/types/intake'
import type { Estimate, VehicleType } from '@/types/intake'
import {
  STATUS_OPTIONS,
  formatDate,
  formatDateTime,
  fromDateTimeLocal,
  toDateTimeLocal
} from '@/utils/intake'

const route = useRoute()
const request = ref<StaffRequestDetail | null>(null)
const loadError = ref(false)

const form = reactive({
  status: 'new' as RequestStatus,
  scheduled_for: '',
  completed_on: '',
  odometer: '',
  final_total: '',
  internal_notes: '',
  vehicle_type: '' as VehicleType | '',
  notify_customer: true
})
const saving = ref(false)
const saveErrors = ref<Record<string, string>>({})
const savedAt = ref<Date | null>(null)

const estimate = computed(() =>
  request.value && 'total' in request.value.estimate ? (request.value.estimate as Estimate) : null
)
const parts = usePartsEstimate(async () => (await fetchStaffRequest(route.params.id as string)).parts_estimate)
const retrying = ref(false)
const retryError = ref('')

async function retryParts() {
  if (!request.value) return
  retrying.value = true
  retryError.value = ''
  try {
    parts.start(await retryPartsEstimate(request.value.id))
  } catch (error) {
    retryError.value =
      axios.isAxiosError(error) && error.response?.data?.detail
        ? error.response.data.detail
        : "Couldn't recalculate. Try again."
  } finally {
    retrying.value = false
  }
}

const vehicleLabel = computed(() => request.value?.vehicle?.label || request.value?.vehicle_label || '')
const smsHref = computed(() => (request.value?.phone ? `sms:${request.value.phone.replace(/[^\d+]/g, '')}` : ''))
const mapsHref = computed(() =>
  request.value?.service_address
    ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(request.value.service_address)}`
    : ''
)
const canNotify = computed(() => !!request.value?.email)

function fillForm(r: StaffRequestDetail) {
  Object.assign(form, {
    status: r.status,
    scheduled_for: toDateTimeLocal(r.scheduled_for),
    completed_on: r.completed_on ?? '',
    odometer: r.odometer?.toString() ?? '',
    final_total: r.final_total ?? '',
    internal_notes: r.internal_notes,
    vehicle_type: r.vehicle_type
  })
}

async function save() {
  if (!request.value) return
  saving.value = true
  saveErrors.value = {}
  try {
    const updated = await updateStaffRequest(request.value.id, {
      status: form.status,
      scheduled_for: fromDateTimeLocal(form.scheduled_for),
      completed_on: form.completed_on || null,
      odometer: form.odometer ? Number(form.odometer) : null,
      ...(invoicePublished.value ? {} : { final_total: form.final_total || null }),
      internal_notes: form.internal_notes,
      vehicle_type: form.vehicle_type,
      notify_customer: canNotify.value && form.notify_customer
    })
    const typeChanged = updated.vehicle_type !== request.value.vehicle_type
    request.value = { ...updated, messages: request.value.messages }
    live.acknowledge(updated.updated_at)
    fillForm(updated)
    // A new vehicle type recalculates the parts estimate server-side.
    if (typeChanged) parts.start({ status: 'pending' })
    savedAt.value = new Date()
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 400) {
      const data = error.response.data as Record<string, string[] | string>
      saveErrors.value = Object.fromEntries(
        Object.entries(data).map(([k, v]) => [k, Array.isArray(v) ? v[0] : v])
      )
    } else {
      saveErrors.value = { detail: "Changes couldn't be saved. Try again." }
    }
  } finally {
    saving.value = false
  }
}

async function send(body: string) {
  if (!request.value) return
  const message = await sendStaffMessage(request.value.id, body)
  request.value.messages = mergeMessages(request.value.messages, [message])
}

// A published invoice drives the final total.
const invoicePublished = computed(() => !!request.value?.invoice?.published_at)

async function onInvoiceSaved(invoice: Invoice | null) {
  if (!request.value) return
  // Saving an invoice can change the final total; reload, keeping form edits.
  const fresh = await fetchStaffRequest(request.value.id)
  request.value = { ...fresh, messages: mergeMessages(request.value.messages, fresh.messages), invoice }
  form.final_total = fresh.final_total ?? ''
  live.acknowledge(fresh.updated_at)
}

// New customer messages appear without a reload. Other changes (e.g. from
// another tab) refresh the request but leave the Manage form alone.
const live = useLiveUpdates({
  poll: (afterId) => pollStaffRequest(request.value!.id, afterId),
  messages: () => request.value?.messages,
  onMessages: (messages) => {
    if (request.value) request.value.messages = mergeMessages(request.value.messages, messages)
  },
  onChanged: async () => {
    if (!request.value) return
    const fresh = await fetchStaffRequest(request.value.id)
    request.value = { ...fresh, messages: mergeMessages(request.value.messages, fresh.messages) }
  }
})

async function copyVin() {
  if (request.value?.vin) await navigator.clipboard?.writeText(request.value.vin)
}

onMounted(async () => {
  try {
    request.value = await fetchStaffRequest(route.params.id as string)
    fillForm(request.value)
    parts.start(request.value.parts_estimate)
    if (request.value.messaging_enabled) live.start(request.value.updated_at)
  } catch {
    loadError.value = true
  }
})

const inputClass =
  'mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-400/40'
const labelClass = 'block text-sm font-medium text-slate-700'
</script>

<template>
  <div class="mx-auto max-w-6xl px-4 py-8 sm:px-6">
    <router-link to="/dashboard" class="text-sm font-medium text-slate-500 hover:text-slate-800">← All bookings</router-link>

    <p v-if="loadError" class="mt-6 rounded-xl bg-red-50 p-4 text-sm text-red-700">This request couldn't be loaded.</p>
    <div v-else-if="!request" class="mt-6 h-64 animate-pulse rounded-2xl bg-slate-200/60" />

    <template v-else>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <h1 class="text-2xl font-bold text-slate-900">#{{ request.id }} · {{ request.name }}</h1>
        <StatusBadge :status="request.status" />
        <span v-if="request.is_emergency" class="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-bold text-red-700">Same-week rush</span>
        <span v-if="request.request_type === 'callback'" class="rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-bold text-violet-700">Contact me</span>
        <span v-if="request.customer_request_count > 1" class="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-bold text-emerald-700">
          Repeat customer · {{ request.customer_request_count }} requests
        </span>
      </div>
      <p class="mt-1 text-sm text-slate-500">Received {{ formatDateTime(request.created_at) }}</p>

      <div class="mt-6 grid gap-6 lg:grid-cols-[1fr_22rem]">
        <div class="space-y-6">
          <!-- Customer & vehicle -->
          <section class="grid gap-6 rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200 sm:grid-cols-2">
            <div>
              <h2 class="text-xs font-semibold uppercase tracking-wider text-slate-400">Customer</h2>
              <p class="mt-2 font-semibold text-slate-900">{{ request.name }}</p>
              <div class="mt-2 space-y-1 text-sm">
                <p v-if="request.phone" class="flex flex-wrap gap-x-3">
                  <a :href="`tel:${request.phone.replace(/[^\d+]/g, '')}`" class="font-medium text-amber-700 hover:underline">{{ request.phone }}</a>
                  <a :href="smsHref" class="text-slate-500 hover:underline">Text</a>
                </p>
                <p v-if="request.email"><a :href="`mailto:${request.email}`" class="text-amber-700 hover:underline">{{ request.email }}</a></p>
                <p v-if="request.service_address">
                  <a :href="mapsHref" target="_blank" rel="noopener" class="text-slate-700 hover:underline">{{ request.service_address }} ↗</a>
                </p>
                <p class="text-xs text-slate-500">
                  {{ request.customer ? `Has an account (${request.customer.email})` : 'Guest, no account yet' }}
                </p>
                <p class="flex flex-wrap gap-1.5 pt-1">
                  <span
                    class="rounded-full px-2 py-0.5 text-xs font-semibold"
                    :class="request.contact_consent ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'"
                  >{{ request.contact_consent ? 'OK to call/text' : 'No contact consent recorded' }}</span>
                  <span
                    class="rounded-full px-2 py-0.5 text-xs font-semibold"
                    :class="request.marketing_consent ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'"
                  >{{ request.marketing_consent ? 'Promos OK' : 'No promos' }}</span>
                </p>
              </div>
            </div>
            <div>
              <h2 class="text-xs font-semibold uppercase tracking-wider text-slate-400">Vehicle</h2>
              <template v-if="request.vin">
                <p class="mt-2 font-semibold text-slate-900">{{ vehicleLabel || 'Not decoded' }}</p>
                <p class="mt-1 flex items-center gap-2 font-mono text-sm tracking-wider text-slate-600">
                  {{ request.vin }}
                  <button type="button" class="font-sans text-xs text-slate-400 hover:text-slate-700" @click="copyVin">Copy</button>
                </p>
              </template>
              <p v-else class="mt-2 text-sm text-slate-500">No VIN given.</p>
              <p class="mt-3 text-sm text-slate-600">
                <template v-if="request.preferred_date">Wants <strong>{{ formatDate(request.preferred_date) }}</strong></template>
              </p>
            </div>
          </section>

          <!-- Work -->
          <section class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">Work requested</h2>
            <div class="mt-3 grid gap-6 md:grid-cols-2">
              <div>
                <ul v-if="request.services.length" class="flex flex-wrap gap-2">
                  <li v-for="s in request.services" :key="s.key" class="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-700">
                    {{ s.name }}<template v-if="s.quantity > 1"> ×{{ s.quantity }}</template>
                  </li>
                </ul>
                <p v-if="request.other_description" class="mt-3 whitespace-pre-wrap text-sm text-slate-700">
                  <span class="font-medium">Other:</span> {{ request.other_description }}
                </p>
                <p v-if="request.notes" class="mt-3 whitespace-pre-wrap rounded-xl bg-amber-50 p-3 text-sm text-slate-800">{{ request.notes }}</p>
              </div>
              <EstimateBreakdown v-if="estimate" :estimate="estimate" />
            </div>
          </section>

          <!-- Parts -->
          <section v-if="request.request_type === 'booking'" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <div class="mb-3 flex items-center justify-between gap-3">
              <h2 class="font-semibold text-slate-900">Parts estimate</h2>
              <button
                v-if="parts.estimate.value?.status !== 'pending'"
                type="button"
                :disabled="retrying"
                class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-50"
                @click="retryParts"
              >
                {{ retrying ? 'Recalculating…' : 'Recalculate' }}
              </button>
            </div>
            <PartsEstimateCard
              v-if="parts.estimate.value"
              :estimate="parts.estimate.value"
              :labor-total="estimate?.total ?? null"
              :vehicle-label="vehicleLabel"
            />
            <p v-else class="text-sm text-slate-600">No parts estimate yet. Add prices to the table, then recalculate.</p>
            <p v-if="retryError" class="mt-2 text-sm text-red-600">{{ retryError }}</p>
            <p class="mt-2 text-xs text-slate-500">
              The customer sees this same estimate. Recalculate after adding prices in the
              <a href="/admin/intake/partpriceexample/" class="underline hover:text-slate-700">price table</a>.
            </p>
          </section>

          <!-- Invoice -->
          <section class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">Invoice</h2>
            <p class="mt-1 text-sm text-slate-500">
              Add or remove work, enter what parts and shipping really cost, then publish. The customer sees it in their garage.
            </p>
            <InvoiceEditor
              class="mt-4"
              :request-id="request.id"
              :can-email="canNotify"
              :parts-estimate="parts.estimate.value"
              @saved="onInvoiceSaved"
            />
          </section>

          <!-- Messages (off unless INTAKE_MESSAGING_ENABLED is set) -->
          <section v-if="request.messaging_enabled" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 class="font-semibold text-slate-900">Messages</h2>
            <p v-if="!request.email" class="mt-1 text-sm text-amber-700">
              No email on file, so replies won't reach them. Call or text instead.
            </p>
            <p v-else class="mt-1 text-sm text-slate-500">Replies are emailed to {{ request.email }}.</p>
            <div class="mt-4">
              <MessageThread :messages="request.messages" viewer="staff" :send="send" placeholder="Reply to the customer…" hint="⌘/Ctrl + Enter to send" />
            </div>
          </section>
        </div>

        <!-- Manage -->
        <aside class="lg:sticky lg:top-6 lg:self-start">
          <form class="space-y-4 rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200" @submit.prevent="save">
            <h2 class="font-semibold text-slate-900">Manage</h2>
            <div>
              <label for="status" :class="labelClass">Status</label>
              <select id="status" v-model="form.status" :class="inputClass">
                <option v-for="option in STATUS_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </div>
            <div>
              <label for="scheduled_for" :class="labelClass">Appointment</label>
              <input id="scheduled_for" v-model="form.scheduled_for" type="datetime-local" :class="inputClass" />
              <p v-if="saveErrors.scheduled_for" class="mt-1 text-sm text-red-600">{{ saveErrors.scheduled_for }}</p>
            </div>
            <div>
              <label for="vehicle_type" :class="labelClass">Vehicle type (for parts)</label>
              <select id="vehicle_type" v-model="form.vehicle_type" :class="inputClass">
                <option value="">Unknown</option>
                <option v-for="type in VEHICLE_TYPES" :key="type.value" :value="type.value">{{ type.label }}</option>
              </select>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="odometer" :class="labelClass">Odometer</label>
                <input id="odometer" v-model="form.odometer" type="number" min="0" inputmode="numeric" placeholder="mi" :class="inputClass" />
              </div>
              <div>
                <label for="final_total" :class="labelClass">Final total</label>
                <input
                  id="final_total"
                  v-model="form.final_total"
                  type="number"
                  min="0"
                  step="0.01"
                  inputmode="decimal"
                  placeholder="$"
                  :disabled="invoicePublished"
                  :title="invoicePublished ? 'Set by the published invoice' : undefined"
                  :class="[inputClass, invoicePublished && 'bg-slate-100 text-slate-500']"
                />
              </div>
            </div>
            <div v-if="form.status === 'completed'">
              <label for="completed_on" :class="labelClass">Completed on</label>
              <input id="completed_on" v-model="form.completed_on" type="date" :class="inputClass" />
              <p class="mt-1 text-xs text-slate-500">Defaults to today when left blank.</p>
            </div>
            <div>
              <label for="internal_notes" :class="labelClass">Private notes</label>
              <textarea
                id="internal_notes"
                v-model="form.internal_notes"
                rows="4"
                placeholder="Parts ordered, part numbers, quotes… never shown to the customer."
                :class="inputClass"
              />
            </div>
            <label class="flex items-start gap-2 text-sm text-slate-700" :class="!canNotify && 'opacity-50'">
              <input v-model="form.notify_customer" type="checkbox" class="mt-0.5 accent-amber-500" :disabled="!canNotify" />
              <span>Email the customer if the status or appointment time changes</span>
            </label>
            <p v-if="saveErrors.detail" class="text-sm text-red-600">{{ saveErrors.detail }}</p>
            <p v-for="(message, field) in saveErrors" v-show="!['detail', 'scheduled_for'].includes(String(field))" :key="field" class="text-sm text-red-600">
              {{ field }}: {{ message }}
            </p>
            <button type="submit" :disabled="saving" class="w-full rounded-xl bg-slate-900 px-4 py-2.5 font-semibold text-white hover:bg-slate-800 disabled:opacity-60">
              {{ saving ? 'Saving…' : 'Save changes' }}
            </button>
            <p v-if="savedAt" class="text-center text-xs text-emerald-700">Saved {{ savedAt.toLocaleTimeString() }}</p>
          </form>
        </aside>
      </div>
    </template>
  </div>
</template>
