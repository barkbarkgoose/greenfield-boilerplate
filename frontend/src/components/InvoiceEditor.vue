<script setup lang="ts">
// Staff-only: build the verified invoice for a request. Jobs come from the
// catalog and are repriced server-side (bundles and deals still apply); the
// lines are what you actually paid for parts and shipping, plus extra labor
// and adjustments. The customer sees it in their garage once published.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import axios from 'axios'
import InvoiceCard from '@/components/InvoiceCard.vue'
import { deleteInvoice, fetchInvoice, previewInvoice, saveInvoice } from '@/services/garage'
import { fetchCatalog } from '@/services/intake'
import { INVOICE_LINE_KINDS } from '@/types/garage'
import type { Invoice, InvoiceInput, InvoiceLineKind } from '@/types/garage'
import type { Catalog, PartsEstimate } from '@/types/intake'
import { formatDateTime, formatMoney } from '@/utils/intake'

const props = defineProps<{
  requestId: number
  canEmail: boolean
  partsEstimate: PartsEstimate | null
}>()
const emit = defineEmits<{ saved: [invoice: Invoice | null] }>()

const KIND_LABELS: Record<InvoiceLineKind, string> = {
  part: 'Part',
  shipping: 'Shipping',
  labor: 'Extra labor',
  adjustment: 'Adjustment'
}
const PLACEHOLDERS: Record<InvoiceLineKind, string> = {
  part: 'e.g. Akebono ACT905 ceramic pads (RockAuto)',
  shipping: 'e.g. RockAuto shipping',
  labor: 'e.g. Replace sway bar links',
  adjustment: 'e.g. Repeat customer discount (use a negative price)'
}

interface EditableLine {
  id: number
  kind: InvoiceLineKind
  description: string
  quantity: string
  unit_price: string
}

const catalog = ref<Catalog | null>(null)
const saved = ref<Invoice | null>(null)
const preview = ref<Invoice | null>(null)
const loadError = ref(false)

const jobs = reactive<Record<string, number>>({})
const draft = reactive({ charge_rush_fee: false, note: '' })
const lines = ref<EditableLine[]>([])
const notifyCustomer = ref(true)
let nextLineId = 1

const saving = ref(false)
const errors = ref<{ detail?: string; lines?: Record<number, Record<string, string>>; fields?: Record<string, string> }>({})
const dirty = ref(false)

const isPublished = computed(() => !!saved.value?.published_at)

function input(published: boolean): InvoiceInput {
  return {
    services: Object.entries(jobs).map(([key, quantity]) => ({ key, quantity })),
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
  for (const key of Object.keys(jobs)) delete jobs[key]
  for (const service of invoice.services) jobs[service.key] = service.quantity
  draft.charge_rush_fee = invoice.charge_rush_fee
  draft.note = invoice.note
  lines.value = invoice.lines.map((line) => ({ id: nextLineId++, ...line }))
  // Changing a loaded invoice is "dirty"; loading it isn't.
  queueMicrotask(() => (dirty.value = false))
}

function toggleJob(key: string) {
  if (jobs[key]) delete jobs[key]
  else jobs[key] = 1
}

function addLine(kind: InvoiceLineKind, description = '', unitPrice = '', quantity = '1') {
  lines.value.push({ id: nextLineId++, kind, description, quantity, unit_price: unitPrice })
}

function addLaborLine() {
  addLine('labor', '', catalog.value?.labor_rate ?? '')
}

function removeLine(id: number) {
  lines.value = lines.value.filter((line) => line.id !== id)
}

// Starting point only: estimated typical prices, to replace with what you paid.
const estimatedParts = computed(() =>
  props.partsEstimate?.status === 'ready' ? props.partsEstimate.services ?? [] : []
)
function addEstimatedParts() {
  for (const service of estimatedParts.value) {
    const label = service.quantity > 1 ? `${service.name} ×${service.quantity}` : service.name
    addLine('part', `${label} (estimate, replace with actual)`, service.typical)
  }
}

function lineAmount(line: EditableLine) {
  const amount = Number(line.quantity) * Number(line.unit_price)
  return Number.isFinite(amount) ? amount.toFixed(2) : '0.00'
}

// --- Live preview --------------------------------------------------------------

let previewTimer: ReturnType<typeof setTimeout> | undefined
let previewRequest = 0
watch(
  [jobs, draft, lines],
  () => {
    dirty.value = true
    clearTimeout(previewTimer)
    previewTimer = setTimeout(async () => {
      const id = ++previewRequest
      try {
        const result = await previewInvoice(props.requestId, input(false))
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
      .map(([field, value]) => [field, Array.isArray(value) ? String(value[0]) : String(value)])
  )
  if (Array.isArray(data.lines)) result.fields.lines = String(data.lines[0])
  return result
}

// --- Save ------------------------------------------------------------------------

async function save(published: boolean) {
  saving.value = true
  try {
    const invoice = await saveInvoice(props.requestId, input(published))
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
    await deleteInvoice(props.requestId)
    load(await fetchInvoice(props.requestId))
    emit('saved', null)
  } catch {
    errors.value = { detail: "Couldn't delete the invoice. Try again." }
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    const [invoice, loadedCatalog] = await Promise.all([fetchInvoice(props.requestId), fetchCatalog()])
    catalog.value = loadedCatalog
    load(invoice)
  } catch {
    loadError.value = true
  }
})

const inputClass =
  'block w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm shadow-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-400/40'
</script>

<template>
  <div class="invoice-editor">
    <p v-if="loadError" class="text-sm text-red-600">The invoice couldn't be loaded.</p>
    <div v-else-if="!catalog || !preview" class="h-40 animate-pulse rounded-xl bg-slate-100" />

    <div v-else class="space-y-6">
      <div class="space-y-6">
        <!-- Status -->
        <p class="text-sm">
          <span
            v-if="isPublished"
            class="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-bold text-emerald-700"
          >Published {{ formatDateTime(saved!.published_at!) }}</span>
          <span v-else-if="saved" class="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-bold text-slate-600">Draft, not visible to the customer</span>
          <span v-else class="text-slate-500">No invoice yet. This starts from the requested work.</span>
          <span v-if="dirty && saved" class="ml-2 text-xs font-medium text-amber-700">Unsaved changes</span>
        </p>

        <!-- Jobs -->
        <fieldset>
          <legend class="text-sm font-semibold text-slate-900">Work done</legend>
          <p class="text-xs text-slate-500">Catalog jobs at book prices. Bundles, free add-ons and the volume rate apply automatically.</p>
          <div class="mt-3 grid gap-2 sm:grid-cols-2">
            <label
              v-for="service in catalog.services"
              :key="service.key"
              class="flex items-center gap-2 rounded-lg px-3 py-2 text-sm ring-1"
              :class="jobs[service.key] ? 'bg-amber-50 ring-amber-300' : 'ring-slate-200 hover:bg-slate-50'"
            >
              <input type="checkbox" class="accent-amber-500" :checked="!!jobs[service.key]" @change="toggleJob(service.key)" />
              <span class="flex-1">{{ service.name }}</span>
              <select
                v-if="jobs[service.key] && service.max_quantity > 1"
                v-model.number="jobs[service.key]"
                class="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs"
                :aria-label="`${service.name} quantity`"
                @click.stop
              >
                <option v-for="n in service.max_quantity" :key="n" :value="n">{{ n }} {{ service.unit ?? '' }}{{ n > 1 && service.unit ? 's' : '' }}</option>
              </select>
              <span v-if="!service.quote_required" class="text-xs text-slate-500">{{ formatMoney(service.price) }}</span>
            </label>
          </div>
          <p v-if="jobs.other" class="mt-2 text-xs text-amber-700">"Other" has no set price. Add what you did as an extra labor line below.</p>
          <label class="mt-3 flex items-center gap-2 text-sm text-slate-700">
            <input v-model="draft.charge_rush_fee" type="checkbox" class="accent-amber-500" />
            Charge the same-week rush fee ({{ formatMoney(catalog.emergency_fee) }})
          </label>
          <p v-if="errors.fields?.services" class="mt-1 text-sm text-red-600">{{ errors.fields.services }}</p>
        </fieldset>

        <!-- Lines -->
        <fieldset>
          <legend class="text-sm font-semibold text-slate-900">Parts, shipping and other charges</legend>
          <p class="text-xs text-slate-500">Enter what you actually paid. Parts are billed at cost.</p>

          <div v-if="lines.length" class="mt-3 space-y-3">
            <div v-for="(line, index) in lines" :key="line.id" class="rounded-xl p-3 ring-1 ring-slate-200">
              <div class="grid gap-2 sm:grid-cols-[8rem_1fr]">
                <select v-model="line.kind" :class="inputClass" :aria-label="`Line ${index + 1} type`">
                  <option v-for="kind in INVOICE_LINE_KINDS" :key="kind" :value="kind">{{ KIND_LABELS[kind] }}</option>
                </select>
                <input
                  v-model="line.description"
                  type="text"
                  maxlength="200"
                  :placeholder="PLACEHOLDERS[line.kind]"
                  :class="inputClass"
                  :aria-label="`Line ${index + 1} description`"
                />
              </div>
              <div class="mt-2 flex flex-wrap items-center gap-2">
                <label class="flex items-center gap-1 text-xs text-slate-500">
                  {{ line.kind === 'labor' ? 'Hours' : 'Qty' }}
                  <input v-model="line.quantity" type="number" min="0.01" step="0.01" inputmode="decimal" :class="[inputClass, 'w-20']" />
                </label>
                <label class="flex items-center gap-1 text-xs text-slate-500">
                  {{ line.kind === 'labor' ? 'Rate $' : 'Each $' }}
                  <input v-model="line.unit_price" type="number" step="0.01" inputmode="decimal" :class="[inputClass, 'w-24']" />
                </label>
                <span class="ml-auto text-sm font-medium text-slate-900">{{ formatMoney(lineAmount(line)) }}</span>
                <button type="button" class="rounded px-2 py-1 text-xs text-slate-400 hover:bg-red-50 hover:text-red-700" @click="removeLine(line.id)">Remove</button>
              </div>
              <p v-for="(message, field) in errors.lines?.[index]" :key="field" class="mt-1 text-xs text-red-600">{{ field }}: {{ message }}</p>
            </div>
          </div>

          <div class="mt-3 flex flex-wrap gap-2">
            <button type="button" class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-slate-300 hover:bg-slate-50" @click="addLine('part')">+ Part</button>
            <button type="button" class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-slate-300 hover:bg-slate-50" @click="addLine('shipping', 'Shipping')">+ Shipping</button>
            <button type="button" class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-slate-300 hover:bg-slate-50" @click="addLaborLine">+ Extra labor</button>
            <button type="button" class="rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-slate-300 hover:bg-slate-50" @click="addLine('adjustment')">+ Adjustment</button>
            <button
              v-if="estimatedParts.length"
              type="button"
              class="rounded-lg px-3 py-1.5 text-sm font-medium text-amber-800 ring-1 ring-amber-300 hover:bg-amber-50"
              @click="addEstimatedParts"
            >
              + Parts from estimate
            </button>
          </div>
          <p v-if="errors.fields?.lines" class="mt-1 text-sm text-red-600">{{ errors.fields.lines }}</p>
        </fieldset>

        <div>
          <label for="invoice-note" class="text-sm font-semibold text-slate-900">Note to the customer</label>
          <textarea
            id="invoice-note"
            v-model="draft.note"
            rows="2"
            maxlength="2000"
            placeholder="e.g. Rear pads have about 30% left; worth doing next visit."
            :class="[inputClass, 'mt-1']"
          />
        </div>
      </div>

      <!-- Preview & actions -->
      <div class="grid gap-4 border-t border-slate-100 pt-6 md:grid-cols-[1fr_15rem]">
        <div class="rounded-2xl bg-slate-50 p-4 ring-1 ring-slate-200">
          <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">Customer sees</p>
          <InvoiceCard :invoice="preview" preview />
        </div>

        <div class="space-y-4">
        <p v-if="errors.detail" class="text-sm text-red-600">{{ errors.detail }}</p>
        <label v-if="!isPublished" class="flex items-start gap-2 text-sm text-slate-700" :class="!canEmail && 'opacity-50'">
          <input v-model="notifyCustomer" type="checkbox" class="mt-0.5 accent-amber-500" :disabled="!canEmail" />
          <span>Email the invoice to the customer when I publish</span>
        </label>
        <div class="flex flex-col gap-2">
          <template v-if="isPublished">
            <button type="button" :disabled="saving" class="rounded-xl bg-slate-900 px-4 py-2.5 font-semibold text-white hover:bg-slate-800 disabled:opacity-60" @click="save(true)">
              {{ saving ? 'Saving…' : 'Save changes' }}
            </button>
            <p class="text-xs text-slate-500">The customer sees changes as soon as you save.</p>
            <button type="button" :disabled="saving" class="rounded-xl px-4 py-2 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-60" @click="save(false)">
              Unpublish (back to draft)
            </button>
          </template>
          <template v-else>
            <button type="button" :disabled="saving" class="rounded-xl bg-emerald-600 px-4 py-2.5 font-semibold text-white hover:bg-emerald-700 disabled:opacity-60" @click="save(true)">
              {{ saving ? 'Saving…' : 'Publish to customer' }}
            </button>
            <button type="button" :disabled="saving" class="rounded-xl px-4 py-2 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-60" @click="save(false)">
              Save draft
            </button>
          </template>
          <button v-if="saved" type="button" :disabled="saving" class="text-sm font-medium text-slate-400 hover:text-red-700" @click="discard">
            Delete invoice
          </button>
        </div>
        <p class="text-xs text-slate-500">Publishing sets the request's final total to the invoice total.</p>
        </div>
      </div>
    </div>
  </div>
</template>
