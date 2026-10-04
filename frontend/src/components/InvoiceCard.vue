<script setup lang="ts">
// A verified invoice: what was delivered (material + per-load delivery,
// priced like the order quote) plus the services, fees and adjustments staff
// added. Used on the customer's order page and as the staff preview.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import QuoteBreakdown from '@/components/QuoteBreakdown.vue'
import { INVOICE_LINE_KINDS } from '@/types/account'
import type { Invoice } from '@/types/account'
import { formatDate, formatMoney } from '@/utils/format'

const props = defineProps<{ invoice: Invoice; preview?: boolean }>()
const { t } = useI18n()

const hasDelivered = computed(() => props.invoice.priced.line_items.length > 0 || props.invoice.priced.deliveries.length > 0)

const groups = computed(() =>
  INVOICE_LINE_KINDS.map((kind) => ({
    kind,
    lines: props.invoice.lines.filter((line) => line.kind === kind)
  })).filter((group) => group.lines.length > 0)
)

// Edited after it was first sent to the customer.
const updatedLater = computed(() => {
  const { published_at: published, updated_at: updated } = props.invoice
  return !!published && !!updated && new Date(updated).getTime() - new Date(published).getTime() > 60_000
})
</script>

<template>
  <div class="invoice-card">
    <p v-if="invoice.published_at && !preview" class="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-200">
      <svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path fill-rule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-8 8a1 1 0 01-1.4 0l-4-4a1 1 0 111.4-1.4L8 12.6l7.3-7.3a1 1 0 011.4 0z" clip-rule="evenodd" />
      </svg>
      {{ t('invoice-card__verified', { date: formatDate(invoice.published_at) }) }}
    </p>
    <p v-if="updatedLater && !preview" class="mt-1 text-xs text-stone-500">
      {{ t('invoice-card__updated', { date: formatDate(invoice.updated_at!) }) }}
    </p>

    <div v-if="hasDelivered" class="mt-4">
      <h3 class="text-xs font-semibold uppercase tracking-wider text-stone-400">{{ t('invoice-card__section--delivered') }}</h3>
      <QuoteBreakdown class="mt-2" :quote="invoice.priced" :total-label="t('invoice-card__delivered-total')" />
    </div>

    <div v-for="group in groups" :key="group.kind" class="mt-4">
      <h3 class="text-xs font-semibold uppercase tracking-wider text-stone-400">{{ t(`invoice-card__section--${group.kind}`) }}</h3>
      <ul class="mt-2 space-y-1.5 text-sm">
        <li v-for="(line, index) in group.lines" :key="index" class="flex justify-between gap-3 text-stone-600">
          <span class="min-w-0 break-words">
            {{ line.description }}
            <span v-if="line.quantity !== '1'" class="whitespace-nowrap text-stone-400">
              · {{ t('invoice-card__quantity', { quantity: line.quantity, price: formatMoney(line.unit_price) }) }}
            </span>
          </span>
          <span class="whitespace-nowrap" :class="Number(line.amount) < 0 && 'text-emerald-700'">
            {{ Number(line.amount) < 0 ? `−${formatMoney(line.amount.slice(1))}` : formatMoney(line.amount) }}
          </span>
        </li>
      </ul>
    </div>

    <p class="mt-4 flex items-baseline justify-between gap-3 border-t border-stone-200 pt-3 text-lg font-bold text-stone-900">
      <span>{{ t('invoice-card__total') }}</span>
      <span>{{ formatMoney(invoice.totals.total) }}</span>
    </p>

    <p v-if="invoice.note" class="mt-3 whitespace-pre-wrap rounded-xl bg-stone-50 p-3 text-sm text-stone-700">{{ invoice.note }}</p>
  </div>
</template>
