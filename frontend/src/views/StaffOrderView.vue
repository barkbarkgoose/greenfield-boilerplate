<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import QuoteBreakdown from '@/components/QuoteBreakdown.vue'
import InvoiceEditor from '@/components/InvoiceEditor.vue'
import MessageThread from '@/components/MessageThread.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { mergeMessages, useLiveUpdates } from '@/composables/useLiveUpdates'
import {
  assignLoad,
  fetchDispatchBoard,
  fetchStaffOrder,
  pollStaffOrder,
  replanOrder,
  sendStaffMessage,
  updateStaffOrder
} from '@/services/account'
import type { BoardTruck, DispatchBoard, Invoice, OrderStatus, StaffOrderDetail } from '@/types/account'
import { DELIVERY_WINDOWS } from '@/types/intake'
import type { DeliveryWindow, Quote } from '@/types/intake'
import { STATUS_OPTIONS, formatDate, formatDateTime, isoDateFromToday } from '@/utils/format'

const route = useRoute()
const order = ref<StaffOrderDetail | null>(null)
const loadError = ref(false)

const WINDOW_LABELS: Record<DeliveryWindow, string> = { any: 'Any time', morning: 'Morning', afternoon: 'Afternoon' }
const COVERAGE_LABELS: Record<string, string> = {
  serve: 'In our area',
  contact: 'Special request area',
  outside: 'Outside our area'
}

const form = reactive({
  status: 'new' as OrderStatus,
  scheduled_date: '',
  delivery_window: 'any' as DeliveryWindow,
  delivered_on: '',
  final_total: '',
  internal_notes: '',
  notify_customer: true
})
const saving = ref(false)
const saveErrors = ref<Record<string, string>>({})
const savedAt = ref<Date | null>(null)

const quote = computed(() => (order.value && 'total' in order.value.quote ? (order.value.quote as Quote) : null))
const deliveryDate = computed(() => order.value?.scheduled_date || order.value?.preferred_date || null)
const smsHref = computed(() => (order.value?.phone ? `sms:${order.value.phone.replace(/[^\d+]/g, '')}` : ''))
const mapsHref = computed(() => {
  const address = [order.value?.delivery_address, order.value?.zip_code].filter(Boolean).join(' ')
  return address ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}` : ''
})
const canNotify = computed(() => !!order.value?.email)

function fillForm(o: StaffOrderDetail) {
  Object.assign(form, {
    status: o.status,
    scheduled_date: o.scheduled_date ?? '',
    delivery_window: o.delivery_window,
    delivered_on: o.delivered_on ?? '',
    final_total: o.final_total ?? '',
    internal_notes: o.internal_notes
  })
}

function errorsFrom(error: unknown, fallback: string): Record<string, string> {
  if (axios.isAxiosError(error) && error.response?.status === 400) {
    const data = error.response.data as Record<string, string[] | string>
    return Object.fromEntries(Object.entries(data).map(([k, v]) => [k, Array.isArray(v) ? v[0] : v]))
  }
  return { detail: fallback }
}

function replaceOrder(fresh: StaffOrderDetail) {
  order.value = { ...fresh, messages: mergeMessages(order.value?.messages ?? [], fresh.messages) }
  live.acknowledge(fresh.updated_at)
}

async function save() {
  if (!order.value) return
  saving.value = true
  saveErrors.value = {}
  const dateBefore = deliveryDate.value
  try {
    const updated = await updateStaffOrder(order.value.id, {
      status: form.status,
      scheduled_date: form.scheduled_date || null,
      delivery_window: form.delivery_window,
      delivered_on: form.delivered_on || null,
      ...(invoicePublished.value ? {} : { final_total: form.final_total || null }),
      internal_notes: form.internal_notes,
      notify_customer: canNotify.value && form.notify_customer
    })
    replaceOrder(updated)
    fillForm(updated)
    savedAt.value = new Date()
    if (deliveryDate.value !== dateBefore) loadBoard()
  } catch (error) {
    saveErrors.value = errorsFrom(error, "Changes couldn't be saved. Try again.")
  } finally {
    saving.value = false
  }
}

// --- Dispatch -------------------------------------------------------------------

// The day's board gives each truck's booked time, for the reassign menu.
const board = ref<DispatchBoard | null>(null)
const dispatchError = ref('')
const dispatchBusy = ref(false)

async function loadBoard() {
  try {
    board.value = await fetchDispatchBoard(deliveryDate.value ?? isoDateFromToday(0))
  } catch {
    board.value = null
  }
}

// Trucks at yards with a saved distance to this zip (others can't be routed there).
const truckOptions = computed(() => {
  const listed = new Set(order.value?.area.yards.map((y) => y.code) ?? [])
  return (board.value?.yards ?? [])
    .filter((yard) => listed.has(yard.code))
    .flatMap((yard) => yard.trucks.map((truck) => ({ yard, truck })))
})

function truckLabel(yardName: string, truck: BoardTruck) {
  const off = !truck.active ? ' · out of service' : truck.day_off ? ' · off that day' : ''
  return `${truck.name} · ${yardName} · ${truck.capacity_yards} yd · ${truck.used_minutes}/${truck.workday_minutes} min${off}`
}

async function reassign(loadId: number, value: string) {
  if (!order.value) return
  dispatchBusy.value = true
  dispatchError.value = ''
  try {
    replaceOrder(await assignLoad(order.value.id, loadId, value ? Number(value) : null))
    loadBoard()
  } catch (error) {
    dispatchError.value = Object.values(errorsFrom(error, "Couldn't move that load."))[0]
  } finally {
    dispatchBusy.value = false
  }
}

async function replan() {
  if (!order.value) return
  if (order.value.loads.some((l) => l.truck) && !window.confirm('Route this order again from scratch? Hand-picked trucks are replaced.')) return
  dispatchBusy.value = true
  dispatchError.value = ''
  try {
    replaceOrder(await replanOrder(order.value.id))
    loadBoard()
  } catch (error) {
    dispatchError.value = Object.values(errorsFrom(error, "Couldn't re-plan this order."))[0]
  } finally {
    dispatchBusy.value = false
  }
}

const loadMinutes = computed(() => order.value?.loads.reduce((sum, l) => sum + (l.truck ? l.minutes : 0), 0) ?? 0)

// --- Messages, invoice, live updates ----------------------------------------------

async function send(body: string) {
  if (!order.value) return
  const message = await sendStaffMessage(order.value.id, body)
  order.value.messages = mergeMessages(order.value.messages, [message])
}

// A published invoice drives the final total.
const invoicePublished = computed(() => !!order.value?.invoice?.published_at)

async function onInvoiceSaved(invoice: Invoice | null) {
  if (!order.value) return
  // Saving an invoice can change the final total; reload, keeping form edits.
  const fresh = await fetchStaffOrder(order.value.id)
  replaceOrder({ ...fresh, invoice })
  form.final_total = fresh.final_total ?? ''
}

// New customer messages appear without a reload. Other changes (e.g. from
// another tab) refresh the order but leave the Manage form alone.
const live = useLiveUpdates({
  poll: (afterId) => pollStaffOrder(order.value!.id, afterId),
  messages: () => order.value?.messages,
  onMessages: (messages) => {
    if (order.value) order.value.messages = mergeMessages(order.value.messages, messages)
  },
  onChanged: async () => {
    if (!order.value) return
    const fresh = await fetchStaffOrder(order.value.id)
    order.value = { ...fresh, messages: mergeMessages(order.value.messages, fresh.messages) }
  }
})

onMounted(async () => {
  try {
    order.value = await fetchStaffOrder(route.params.id as string)
    fillForm(order.value)
    loadBoard()
    if (order.value.messaging_enabled) live.start(order.value.updated_at)
  } catch {
    loadError.value = true
  }
})

const inputClass =
  'mt-1 block w-full rounded-lg border border-stone-300 px-3 py-2 text-sm shadow-sm focus:border-lime-600 focus:outline-none focus:ring-2 focus:ring-lime-500/40'
const labelClass = 'block text-sm font-medium text-stone-700'
const cardClass = 'rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200'
</script>

<template>
  <div class="mx-auto max-w-6xl px-4 py-8 sm:px-6">
    <router-link to="/dashboard" class="text-sm font-medium text-stone-500 hover:text-stone-800">← All orders</router-link>

    <p v-if="loadError" class="mt-6 rounded-xl bg-red-50 p-4 text-sm text-red-700">This order couldn't be loaded.</p>
    <div v-else-if="!order" class="mt-6 h-64 animate-pulse rounded-2xl bg-stone-200/60" />

    <template v-else>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <h1 class="text-2xl font-bold text-stone-900">#{{ order.id }} · {{ order.name }}</h1>
        <StatusBadge :status="order.status" />
        <span v-if="order.is_rush" class="rounded-full bg-orange-100 px-2.5 py-0.5 text-xs font-bold text-orange-700">Rush</span>
        <span v-if="order.request_type === 'callback'" class="rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-bold text-violet-700">Special request</span>
        <span v-if="order.customer_order_count > 1" class="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-bold text-emerald-700">
          Repeat customer · {{ order.customer_order_count }} orders
        </span>
      </div>
      <p class="mt-1 text-sm text-stone-500">Received {{ formatDateTime(order.created_at) }}</p>

      <div class="mt-6 grid gap-6 lg:grid-cols-[1fr_22rem]">
        <div class="space-y-6">
          <!-- Customer & delivery -->
          <section class="grid gap-6 sm:grid-cols-2" :class="cardClass">
            <div>
              <h2 class="text-xs font-semibold uppercase tracking-wider text-stone-400">Customer</h2>
              <p class="mt-2 font-semibold text-stone-900">{{ order.name }}</p>
              <div class="mt-2 space-y-1 text-sm">
                <p v-if="order.phone" class="flex flex-wrap gap-x-3">
                  <a :href="`tel:${order.phone.replace(/[^\d+]/g, '')}`" class="font-medium text-lime-700 hover:underline">{{ order.phone }}</a>
                  <a :href="smsHref" class="text-stone-500 hover:underline">Text</a>
                </p>
                <p v-if="order.email"><a :href="`mailto:${order.email}`" class="text-lime-700 hover:underline">{{ order.email }}</a></p>
                <p class="text-xs text-stone-500">
                  {{ order.customer ? `Has an account (${order.customer.email})` : 'Guest, no account yet' }} · {{ order.language === 'es' ? 'Spanish' : 'English' }}
                </p>
                <p class="flex flex-wrap gap-1.5 pt-1">
                  <span class="rounded-full px-2 py-0.5 text-xs font-semibold" :class="order.contact_consent ? 'bg-emerald-50 text-emerald-700' : 'bg-stone-100 text-stone-500'">
                    {{ order.contact_consent ? 'OK to call/text' : 'No contact consent recorded' }}
                  </span>
                  <span class="rounded-full px-2 py-0.5 text-xs font-semibold" :class="order.marketing_consent ? 'bg-emerald-50 text-emerald-700' : 'bg-stone-100 text-stone-500'">
                    {{ order.marketing_consent ? 'Promos OK' : 'No promos' }}
                  </span>
                </p>
              </div>
            </div>
            <div>
              <h2 class="text-xs font-semibold uppercase tracking-wider text-stone-400">Deliver to</h2>
              <p v-if="order.delivery_address || order.zip_code" class="mt-2 font-semibold text-stone-900">
                <a v-if="mapsHref" :href="mapsHref" target="_blank" rel="noopener" class="hover:underline">{{ order.delivery_address }} {{ order.zip_code }} ↗</a>
              </p>
              <p v-else class="mt-2 text-sm text-stone-500">No address given.</p>
              <p v-if="order.zip_code" class="mt-1 text-sm text-stone-600">
                {{ order.area.city || 'Unknown city' }} ·
                <span :class="order.area.status === 'serve' ? 'text-emerald-700' : 'text-amber-700'">{{ COVERAGE_LABELS[order.area.status] }}</span>
              </p>
              <p v-if="order.area.note" class="mt-1 text-xs text-amber-700">{{ order.area.note }}</p>
              <p class="mt-3 text-sm text-stone-600">
                <template v-if="order.preferred_date">Wants <strong>{{ formatDate(order.preferred_date) }}</strong> · {{ WINDOW_LABELS[order.delivery_window] }}</template>
              </p>
            </div>
          </section>

          <!-- Order -->
          <section :class="cardClass">
            <h2 class="font-semibold text-stone-900">Order</h2>
            <div class="mt-3 grid gap-6 md:grid-cols-2">
              <div>
                <ul v-if="order.items.length" class="flex flex-wrap gap-2">
                  <li v-for="item in order.items" :key="item.key" class="rounded-full bg-stone-100 px-3 py-1 text-sm text-stone-700">{{ item.name }} · {{ item.quantity }} yd</li>
                </ul>
                <p v-else class="text-sm text-stone-500">No products picked.</p>
                <p v-if="order.placement_notes" class="mt-3 whitespace-pre-wrap rounded-xl bg-lime-50 p-3 text-sm text-stone-800">
                  <span class="block text-xs font-semibold uppercase tracking-wider text-lime-800">Where to dump it</span>{{ order.placement_notes }}
                </p>
                <p v-if="order.notes" class="mt-3 whitespace-pre-wrap rounded-xl bg-stone-50 p-3 text-sm text-stone-800">{{ order.notes }}</p>
              </div>
              <QuoteBreakdown v-if="quote" :quote="quote" total-label="Quoted total" />
            </div>
          </section>

          <!-- Dispatch -->
          <section v-if="order.request_type === 'delivery' || order.loads.length" :class="cardClass">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 class="font-semibold text-stone-900">Dispatch</h2>
                <p class="text-sm text-stone-500">
                  <template v-if="deliveryDate">
                    {{ formatDate(deliveryDate) }}{{ order.scheduled_date ? '' : ' (wanted, not confirmed)' }} ·
                    <router-link :to="{ name: 'dispatch', query: { date: deliveryDate } }" class="text-lime-700 hover:underline">that day's board</router-link>
                  </template>
                  <template v-else>No date yet.</template>
                </p>
              </div>
              <button
                v-if="order.items.length"
                type="button"
                :disabled="dispatchBusy"
                class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-stone-300 hover:bg-stone-50 disabled:opacity-50"
                @click="replan"
              >
                {{ dispatchBusy ? 'Working…' : 'Re-plan' }}
              </button>
            </div>

            <p v-if="order.plan_status === 'no_capacity'" class="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-800 ring-1 ring-red-200">
              Some loads have no truck. Pick one below, move the date, or call the customer.
            </p>
            <p v-else-if="order.plan_status === 'out_of_stock'" class="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-800 ring-1 ring-red-200">
              A product isn't in stock at any yard that reaches this ZIP. Restock it on the dispatch board, then re-plan.
            </p>

            <ul v-if="order.loads.length" class="mt-4 divide-y divide-stone-100 rounded-xl ring-1 ring-stone-200">
              <li v-for="(load, index) in order.loads" :key="load.id" class="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center">
                <div class="min-w-0 flex-1">
                  <p class="font-medium text-stone-900">Load {{ index + 1 }} · {{ load.quantity }} yd {{ load.product_name.toLowerCase() }}</p>
                  <p class="text-xs text-stone-500">
                    <template v-if="load.yard_name">{{ load.yard_name }} · </template>{{ load.miles }} mi · {{ load.minutes }} min of truck time
                  </p>
                </div>
                <select
                  :value="load.truck ?? ''"
                  :disabled="dispatchBusy"
                  class="w-full rounded-lg border px-2 py-1.5 text-sm sm:w-80"
                  :class="load.truck ? 'border-stone-300' : 'border-red-400 bg-red-50'"
                  :aria-label="`Truck for load ${index + 1}`"
                  @change="reassign(load.id, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">No truck assigned</option>
                  <option v-for="{ yard, truck } in truckOptions" :key="truck.id" :value="truck.id">{{ truckLabel(yard.name, truck) }}</option>
                </select>
              </li>
            </ul>
            <p v-else class="mt-3 text-sm text-stone-500">No loads planned.</p>
            <p v-if="dispatchError" class="mt-2 text-sm text-red-600">{{ dispatchError }}</p>

            <div v-if="order.area.yards.length" class="mt-4 text-xs text-stone-500">
              <p>
                Saved distances to {{ order.zip_code }}:
                <span v-for="(yard, index) in order.area.yards" :key="yard.code">
                  {{ index ? ' · ' : '' }}{{ yard.code }} {{ yard.miles }} mi / {{ yard.minutes }} min
                </span>
              </p>
              <p v-if="loadMinutes">This order takes {{ loadMinutes }} truck minutes in total.</p>
            </div>
          </section>

          <!-- Invoice -->
          <section :class="cardClass">
            <h2 class="font-semibold text-stone-900">Invoice</h2>
            <p class="mt-1 text-sm text-stone-500">Correct the yards and loads to what actually went out, add any extras, then publish.</p>
            <InvoiceEditor class="mt-4" :order-id="order.id" :can-email="canNotify" :dispatched-loads="order.loads" @saved="onInvoiceSaved" />
          </section>

          <!-- Messages (off unless INTAKE_MESSAGING_ENABLED is set) -->
          <section v-if="order.messaging_enabled" :class="cardClass">
            <h2 class="font-semibold text-stone-900">Messages</h2>
            <p v-if="!order.email" class="mt-1 text-sm text-amber-700">No email on file, so replies won't reach them. Call or text instead.</p>
            <p v-else class="mt-1 text-sm text-stone-500">Replies are emailed to {{ order.email }}.</p>
            <div class="mt-4">
              <MessageThread :messages="order.messages" viewer="staff" :send="send" placeholder="Reply to the customer…" hint="⌘/Ctrl + Enter to send" />
            </div>
          </section>
        </div>

        <!-- Manage -->
        <aside class="lg:sticky lg:top-6 lg:self-start">
          <form class="space-y-4" :class="cardClass" @submit.prevent="save">
            <h2 class="font-semibold text-stone-900">Manage</h2>
            <div>
              <label for="status" :class="labelClass">Status</label>
              <select id="status" v-model="form.status" :class="inputClass">
                <option v-for="option in STATUS_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </div>
            <div class="grid grid-cols-[1fr_8rem] gap-3">
              <div>
                <label for="scheduled_date" :class="labelClass">Delivery date</label>
                <input id="scheduled_date" v-model="form.scheduled_date" type="date" :class="inputClass" />
              </div>
              <div>
                <label for="delivery_window" :class="labelClass">Window</label>
                <select id="delivery_window" v-model="form.delivery_window" :class="inputClass">
                  <option v-for="window in DELIVERY_WINDOWS" :key="window" :value="window">{{ WINDOW_LABELS[window] }}</option>
                </select>
              </div>
            </div>
            <p v-if="saveErrors.scheduled_date" class="text-sm text-red-600">{{ saveErrors.scheduled_date }}</p>
            <p class="text-xs text-stone-500">Changing the date moves this order's loads (and their trucks) to that day.</p>
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
                :class="[inputClass, invoicePublished && 'bg-stone-100 text-stone-500']"
              />
            </div>
            <div v-if="form.status === 'delivered'">
              <label for="delivered_on" :class="labelClass">Delivered on</label>
              <input id="delivered_on" v-model="form.delivered_on" type="date" :class="inputClass" />
              <p class="mt-1 text-xs text-stone-500">Defaults to today when left blank.</p>
            </div>
            <div>
              <label for="internal_notes" :class="labelClass">Private notes</label>
              <textarea id="internal_notes" v-model="form.internal_notes" rows="4" placeholder="Gate codes, driver notes, quotes… never shown to the customer." :class="inputClass" />
            </div>
            <label class="flex items-start gap-2 text-sm text-stone-700" :class="!canNotify && 'opacity-50'">
              <input v-model="form.notify_customer" type="checkbox" class="mt-0.5 accent-lime-600" :disabled="!canNotify" />
              <span>Email the customer if the status, date or window changes</span>
            </label>
            <p v-if="saveErrors.detail" class="text-sm text-red-600">{{ saveErrors.detail }}</p>
            <p v-for="(message, field) in saveErrors" v-show="!['detail', 'scheduled_date'].includes(String(field))" :key="field" class="text-sm text-red-600">
              {{ field }}: {{ message }}
            </p>
            <button type="submit" :disabled="saving" class="w-full rounded-xl bg-stone-900 px-4 py-2.5 font-semibold text-white hover:bg-stone-800 disabled:opacity-60">
              {{ saving ? 'Saving…' : 'Save changes' }}
            </button>
            <p v-if="savedAt" class="text-center text-xs text-emerald-700">Saved {{ savedAt.toLocaleTimeString() }}</p>
          </form>
        </aside>
      </div>
    </template>
  </div>
</template>
