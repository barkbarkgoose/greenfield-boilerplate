<script setup lang="ts">
// Staff-only: build the verified invoice for an order. Material and loads are
// repriced server-side from the catalog (per-yard prices, per-load delivery
// by distance); lines cover extra services, fees and adjustments. The
// customer sees it on their order page once published.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import axios from 'axios'
import InvoiceCard from '@/components/InvoiceCard.vue'
import { deleteInvoice, fetchInvoice, previewInvoice, saveInvoice } from '@/services/account'
import { fetchCatalog } from '@/services/intake'
import { INVOICE_LINE_KINDS } from '@/types/account'
import type { Invoice, InvoiceInput, InvoiceLineKind, OrderLoad } from '@/types/account'
import type { Catalog } from '@/types/intake'
import { formatDateTime, formatMoney } from '@/utils/format'

const props = defineProps<{
  orderId: number
  canEmail: boolean
  // The order's dispatched loads, to reset the invoice's loads to.
  dispatchedLoads: OrderLoad[]
}>()
const emit = defineEmits<{ saved: [invoice: Invoice | null] }>()

const KIND_LABELS: Record<InvoiceLineKind, string> = {
  service: 'Service',
  fee: 'Fee',
  adjustment: 'Adjustment'
}
const PLACEHOLDERS: Record<InvoiceLineKind, string> = {
  service: 'e.g. Spread topsoil in back yard (hours)',
  fee: 'e.g. Wait time, second dump spot',
  adjustment: 'e.g. Repeat customer discount (use a negative price)'
}

interface EditableLine {
  id: number
  kind: InvoiceLineKind
  description: string
  quantity: string
  unit_price: string
}

interface EditableLoad {
  id: number
  product: string
  quantity: number
  miles: string
}

const catalog = ref<Catalog | null>(null)
const saved = ref<Invoice | null>(null)
const preview = ref<Invoice | null>(null)
const loadError = ref(false)

const items = reactive<Record<string, number>>({})
const loads = ref<EditableLoad[]>([])
const draft = reactive({ charge_rush_fee: false, note: '' })
const lines = ref<EditableLine[]>([])
const notifyCustomer = ref(true)
let nextId = 1

const saving = ref(false)
const errors = ref<{ detail?: string; lines?: Record<number, Record<string, string>>; fields?: Record<string, string> }>({})
const dirty = ref(false)

const isPublished = computed(() => !!saved.value?.published_at)
const productName = (key: string) => catalog.value?.products.find((p) => p.key === key)?.name ?? key
const loadedYards = computed(() => {
  const totals: Record<string, number> = {}
  for (const load of loads.value) totals[load.product] = (totals[load.product] ?? 0) + Number(load.quantity || 0)
  return totals
})

function input(published: boolean): InvoiceInput {
  return {
    items: Object.entries(items).map(([key, quantity]) => ({ key, quantity })),
    loads: loads.value.map(({ product, quantity, miles }) => ({ product, quantity: Number(quantity) || 0, miles: miles || '0' })),
    charge_rush_fee: draft.charge_rush_fee,
    lines: lines.value.map(({ kind, description, quantity, unit_price }) => ({
      kind,
      description: description.trim(),
      quantity: quantity || '0',
      unit_price: unit_price || '0'
    })),
    note: draft.note.trim(),
    published,
    notify_customer: props.canEmail && notifyCustomer.value
  }
}

function load(invoice: Invoice) {
  saved.value = invoice.exists ? invoice : null
  preview.value = invoice
  for (const key of Object.keys(items)) delete items[key]
  for (const item of invoice.items) items[item.key] = item.quantity
  loads.value = invoice.loads.map((l) => ({ id: nextId++, ...l }))
  draft.charge_rush_fee = invoice.charge_rush_fee
  draft.note = invoice.note
  lines.value = invoice.lines.map((line) => ({ id: nextId++, ...line }))
  // Changing a loaded invoice is "dirty"; loading it isn't.
  queueMicrotask(() => (dirty.value = false))
}

function toggleItem(key: string) {
  if (items[key]) delete items[key]
  else items[key] = 1
}

function addLoad() {
  const product = Object.keys(items)[0] ?? catalog.value?.products[0]?.key ?? ''
  loads.value.push({ id: nextId++, product, quantity: 1, miles: '0' })
}

function resetLoads() {
  loads.value = props.dispatchedLoads.map((l) => ({ id: nextId++, product: l.product, quantity: l.quantity, miles: l.miles }))
}

function addLine(kind: InvoiceLineKind, description = '', unitPrice = '', quantity = '1') {
  lines.value.push({ id: nextId++, kind, description, quantity, unit_price: unitPrice })
}

function lineAmount(line: EditableLine) {
  const amount = Number(line.quantity) * Number(line.unit_price)
  return Number.isFinite(amount) ? amount.toFixed(2) : '0.00'
}

// --- Live preview --------------------------------------------------------------

let previewTimer: ReturnType<typeof setTimeout> | undefined
let previewRequest = 0
watch(
  [items, loads, draft, lines],
  () => {
    dirty.value = true
    clearTimeout(previewTimer)
    previewTimer = setTimeout(async () => {
      const id = ++previewRequest
      try {
        const result = await previewInvoice(props.orderId, input(false))
        if (id === previewRequest) {
          preview.value = { ...result, published_at: saved.value?.published_at ?? null }
          errors.value = {}
        }
      } catch (error) {
        if (id === previewRequest) errors.value = parseErrors(error)
      }
    }, 300)
  },
  { deep: true }
)
onBeforeUnmount(() => clearTimeout(previewTimer))

function parseErrors(error: unknown) {
  if (!axios.isAxiosError(error) || error.response?.status !== 400) {
    return { detail: "Couldn't price the invoice. Try again." }
  }
  const data = error.response.data as Record<string, unknown>
  const result: { lines?: Record<number, Record<string, string>>; fields?: Record<string, string> } = {}
  if (data.lines && typeof data.lines === 'object' && !Array.isArray(data.lines)) {
    result.lines = {}
    for (const [index, fieldErrors] of Object.entries(data.lines as Record<string, Record<string, string[]>>)) {
      result.lines[Number(index)] = Object.fromEntries(
        Object.entries(fieldErrors).map(([field, messages]) => [field, messages[0]])
      )
    }
  }
  result.fields = Object.fromEntries(
    Object.entries(data)
      .filter(([field]) => field !== 'lines')
      .map(([field, value]) => [field, typeof value === 'string' ? value : JSON.stringify(value)])
  )
  if (Array.isArray(data.lines)) result.fields.lines = String(data.lines[0])
  return result
}

// --- Save ------------------------------------------------------------------------

async function save(published: boolean) {
  saving.value = true
  try {
    const invoice = await saveInvoice(props.orderId, input(published))
    clearTimeout(previewTimer)
    previewRequest++
    load(invoice)
    errors.value = {}
    emit('saved', invoice)
  } catch (error) {
    errors.value = parseErrors(error)
  } finally {
    saving.value = false
  }
}

async function discard() {
  if (!window.confirm(isPublished.value ? 'Delete this invoice? The customer will no longer see it.' : 'Delete this draft invoice?')) return
  saving.value = true
  try {
    await deleteInvoice(props.orderId)
    load(await fetchInvoice(props.orderId))
    emit('saved', null)
  } catch {
    errors.value = { detail: "Couldn't delete the invoice. Try again." }
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    const [invoice, loadedCatalog] = await Promise.all([fetchInvoice(props.orderId), fetchCatalog()])
    catalog.value = loadedCatalog
    load(invoice)
  } catch {
    loadError.value = true
  }
})

const fieldClass =
  'rounded-lg border border-stone-300 px-2.5 py-1.5 text-sm shadow-sm focus:border-lime-600 focus:outline-none focus:ring-2 focus:ring-lime-500/40'
const inputClass = `block w-full ${fieldClass}`
</script>

<template>
  <div class="invoice-editor">
    <p v-if="loadError" class="text-sm text-red-600">The invoice couldn't be loaded.</p>
    <div v-else-if="!catalog || !preview" class="h-40 animate-pulse rounded-xl bg-stone-100" />

    <div v-else class="space-y-6">
      <!-- Status -->
      <p class="text-sm">
        <span v-if="isPublished" class="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-bold text-emerald-700">Published {{ formatDateTime(saved!.published_at!) }}</span>
        <span v-else-if="saved" class="rounded-full bg-stone-100 px-2.5 py-0.5 text-xs font-bold text-stone-600">Draft, not visible to the customer</span>
        <span v-else class="text-stone-500">No invoice yet. This starts from the order and its dispatched loads.</span>
        <span v-if="dirty && saved" class="ml-2 text-xs font-medium text-amber-700">Unsaved changes</span>
      </p>

      <!-- Material -->
      <fieldset>
        <legend class="text-sm font-semibold text-stone-900">Material delivered</legend>
        <p class="text-xs text-stone-500">Cubic yards that actually went out, at catalog prices. Order minimums don't apply here.</p>
        <div class="mt-3 grid gap-2 sm:grid-cols-2">
          <label
            v-for="product in catalog.products"
            :key="product.key"
            class="flex items-center gap-2 rounded-lg px-3 py-2 text-sm ring-1"
            :class="items[product.key] ? 'bg-lime-50 ring-lime-300' : 'ring-stone-200 hover:bg-stone-50'"
          >
            <input type="checkbox" class="accent-lime-600" :checked="!!items[product.key]" @change="toggleItem(product.key)" />
            <span class="flex-1">{{ product.name }}</span>
            <input
              v-if="items[product.key]"
              v-model.number="items[product.key]"
              type="number"
              min="1"
              max="200"
              class="w-16 rounded border border-stone-300 bg-white px-1.5 py-0.5 text-xs"
              :aria-label="`${product.name} yards`"
              @click.stop
            />
            <span class="text-xs text-stone-500">{{ formatMoney(product.price_per_yard) }}/yd</span>
          </label>
        </div>
        <p v-if="errors.fields?.items" class="mt-1 text-sm text-red-600">{{ errors.fields.items }}</p>
      </fieldset>

      <!-- Loads -->
      <fieldset>
        <legend class="text-sm font-semibold text-stone-900">Loads (delivery fees)</legend>
        <p class="text-xs text-stone-500">One row per truck trip. Fee = {{ formatMoney(catalog.delivery_base_fee) }} for the first {{ catalog.included_miles }} mi, then {{ formatMoney(catalog.per_mile_fee) }}/mi.</p>
        <div v-if="loads.length" class="mt-3 space-y-2">
          <div v-for="(row, index) in loads" :key="row.id" class="flex flex-wrap items-center gap-2 rounded-lg p-2 ring-1 ring-stone-200">
            <span class="w-6 text-xs text-stone-400">#{{ index + 1 }}</span>
            <select v-model="row.product" :class="[fieldClass, 'w-44']" :aria-label="`Load ${index + 1} product`">
              <option v-for="product in catalog.products" :key="product.key" :value="product.key">{{ product.name }}</option>
            </select>
            <label class="flex items-center gap-1 text-xs text-stone-500">
              yd <input v-model.number="row.quantity" type="number" min="1" max="60" :class="[fieldClass, 'w-16']" />
            </label>
            <label class="flex items-center gap-1 text-xs text-stone-500">
              mi <input v-model="row.miles" type="number" min="0" step="0.1" :class="[fieldClass, 'w-20']" />
            </label>
            <button type="button" class="ml-auto rounded px-2 py-1 text-xs text-stone-400 hover:bg-red-50 hover:text-red-700" @click="loads = loads.filter((l) => l.id !== row.id)">Remove</button>
          </div>
        </div>
        <p
          v-for="(yards, key) in items"
          v-show="(loadedYards[key] ?? 0) !== yards"
          :key="key"
          class="mt-1 text-xs text-amber-700"
        >
          {{ productName(String(key)) }}: {{ yards }} yd delivered but {{ loadedYards[key] ?? 0 }} yd in loads.
        </p>
        <div class="mt-3 flex flex-wrap gap-2">
          <button type="button" class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-stone-300 hover:bg-stone-50" @click="addLoad">+ Load</button>
          <button v-if="dispatchedLoads.length" type="button" class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-stone-300 hover:bg-stone-50" @click="resetLoads">
            Reset to dispatched loads
          </button>
        </div>
        <label class="mt-3 flex items-center gap-2 text-sm text-stone-700">
          <input v-model="draft.charge_rush_fee" type="checkbox" class="accent-lime-600" />
          Charge the rush fee ({{ formatMoney(catalog.rush_fee) }})
        </label>
        <p v-if="errors.fields?.loads" class="mt-1 text-sm text-red-600">{{ errors.fields.loads }}</p>
      </fieldset>

      <!-- Lines -->
      <fieldset>
        <legend class="text-sm font-semibold text-stone-900">Other charges</legend>
        <div v-if="lines.length" class="mt-3 space-y-3">
          <div v-for="(line, index) in lines" :key="line.id" class="rounded-xl p-3 ring-1 ring-stone-200">
            <div class="grid gap-2 sm:grid-cols-[8rem_1fr]">
              <select v-model="line.kind" :class="inputClass" :aria-label="`Line ${index + 1} type`">
                <option v-for="kind in INVOICE_LINE_KINDS" :key="kind" :value="kind">{{ KIND_LABELS[kind] }}</option>
              </select>
              <input v-model="line.description" type="text" maxlength="200" :placeholder="PLACEHOLDERS[line.kind]" :class="inputClass" :aria-label="`Line ${index + 1} description`" />
            </div>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <label class="flex items-center gap-1 text-xs text-stone-500">
                Qty <input v-model="line.quantity" type="number" min="0.01" step="0.01" inputmode="decimal" :class="[fieldClass, 'w-20']" />
              </label>
              <label class="flex items-center gap-1 text-xs text-stone-500">
                Each $ <input v-model="line.unit_price" type="number" step="0.01" inputmode="decimal" :class="[fieldClass, 'w-24']" />
              </label>
              <span class="ml-auto text-sm font-medium text-stone-900">{{ formatMoney(lineAmount(line)) }}</span>
              <button type="button" class="rounded px-2 py-1 text-xs text-stone-400 hover:bg-red-50 hover:text-red-700" @click="lines = lines.filter((l) => l.id !== line.id)">Remove</button>
            </div>
            <p v-for="(message, field) in errors.lines?.[index]" :key="field" class="mt-1 text-xs text-red-600">{{ field }}: {{ message }}</p>
          </div>
        </div>
        <div class="mt-3 flex flex-wrap gap-2">
          <button type="button" class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-stone-300 hover:bg-stone-50" @click="addLine('service')">+ Service</button>
          <button type="button" class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-stone-300 hover:bg-stone-50" @click="addLine('fee')">+ Fee</button>
          <button type="button" class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-stone-300 hover:bg-stone-50" @click="addLine('adjustment')">+ Adjustment</button>
        </div>
        <p v-if="errors.fields?.lines" class="mt-1 text-sm text-red-600">{{ errors.fields.lines }}</p>
      </fieldset>

      <div>
        <label for="invoice-note" class="text-sm font-semibold text-stone-900">Note to the customer</label>
        <textarea id="invoice-note" v-model="draft.note" rows="2" maxlength="2000" placeholder="e.g. Split into two piles as asked." :class="[inputClass, 'mt-1']" />
      </div>

      <!-- Preview & actions -->
      <div class="grid gap-4 border-t border-stone-100 pt-6 md:grid-cols-[1fr_15rem]">
        <div class="rounded-2xl bg-stone-50 p-4 ring-1 ring-stone-200">
          <p class="text-xs font-semibold uppercase tracking-wider text-stone-400">Customer sees</p>
          <InvoiceCard :invoice="preview" preview />
        </div>

        <div class="space-y-4">
          <p v-if="errors.detail" class="text-sm text-red-600">{{ errors.detail }}</p>
          <label v-if="!isPublished" class="flex items-start gap-2 text-sm text-stone-700" :class="!canEmail && 'opacity-50'">
            <input v-model="notifyCustomer" type="checkbox" class="mt-0.5 accent-lime-600" :disabled="!canEmail" />
            <span>Email the invoice to the customer when I publish</span>
          </label>
          <div class="flex flex-col gap-2">
            <template v-if="isPublished">
              <button type="button" :disabled="saving" class="rounded-xl bg-stone-900 px-4 py-2.5 font-semibold text-white hover:bg-stone-800 disabled:opacity-60" @click="save(true)">
                {{ saving ? 'Saving…' : 'Save changes' }}
              </button>
              <p class="text-xs text-stone-500">The customer sees changes as soon as you save.</p>
              <button type="button" :disabled="saving" class="rounded-xl px-4 py-2 text-sm font-semibold text-stone-700 ring-1 ring-stone-300 hover:bg-stone-50 disabled:opacity-60" @click="save(false)">
                Unpublish (back to draft)
              </button>
            </template>
            <template v-else>
              <button type="button" :disabled="saving" class="rounded-xl bg-emerald-600 px-4 py-2.5 font-semibold text-white hover:bg-emerald-700 disabled:opacity-60" @click="save(true)">
                {{ saving ? 'Saving…' : 'Publish to customer' }}
              </button>
              <button type="button" :disabled="saving" class="rounded-xl px-4 py-2 text-sm font-semibold text-stone-700 ring-1 ring-stone-300 hover:bg-stone-50 disabled:opacity-60" @click="save(false)">
                Save draft
              </button>
            </template>
            <button v-if="saved" type="button" :disabled="saving" class="text-sm font-medium text-stone-400 hover:text-red-700" @click="discard">
              Delete invoice
            </button>
          </div>
          <p class="text-xs text-stone-500">Publishing sets the order's final total to the invoice total.</p>
        </div>
      </div>
    </div>
  </div>
</template>
