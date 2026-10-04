<script setup lang="ts">
// Material per yard, then one delivery line per truckload, rush fee, total.
// Used on order pages, invoices and (dark) in the order form's sidebar.
import { useI18n } from 'vue-i18n'
import type { Quote } from '@/types/intake'
import { formatMoney } from '@/utils/format'

withDefaults(defineProps<{ quote: Quote; totalLabel?: string; dark?: boolean }>(), { dark: false })
const { t } = useI18n()
</script>

<template>
  <ul class="quote-breakdown space-y-1.5 text-sm">
    <li v-for="item in quote.line_items" :key="item.key" class="flex justify-between gap-3" :class="dark ? 'text-stone-300' : 'text-stone-600'">
      <span>
        {{ item.name }}
        <span :class="dark ? 'text-stone-400' : 'text-stone-400'">· {{ t('quote-breakdown__yards', { quantity: item.quantity, price: formatMoney(item.unit_price) }) }}</span>
      </span>
      <span class="whitespace-nowrap">{{ formatMoney(item.amount) }}</span>
    </li>
    <li v-if="Number(quote.tax) > 0" class="flex justify-between gap-3" :class="dark ? 'text-stone-300' : 'text-stone-600'">
      <span>{{ t('quote-breakdown__line--tax') }}</span><span>{{ formatMoney(quote.tax) }}</span>
    </li>
    <li
      v-for="(load, index) in quote.deliveries"
      :key="`load-${index}`"
      class="flex justify-between gap-3"
      :class="[dark ? 'text-stone-300' : 'text-stone-600', index === 0 && (dark ? 'border-t border-stone-700 pt-2' : 'border-t border-stone-100 pt-2')]"
    >
      <span>
        {{ t('quote-breakdown__line--delivery', { number: index + 1 }) }}
        <span class="text-stone-400">· {{ t('quote-breakdown__load-detail', { quantity: load.quantity, miles: load.miles }) }}</span>
      </span>
      <span class="whitespace-nowrap">{{ formatMoney(load.fee) }}</span>
    </li>
    <li v-if="Number(quote.rush_fee) > 0" class="flex justify-between gap-3" :class="dark ? 'text-orange-300' : 'text-orange-700'">
      <span>{{ t('quote-breakdown__line--rush') }}</span><span>{{ formatMoney(quote.rush_fee) }}</span>
    </li>
    <li
      class="flex justify-between gap-3 pt-2 font-semibold"
      :class="dark ? 'border-t border-stone-700 text-white' : 'border-t border-stone-100 text-stone-900'"
    >
      <span>{{ totalLabel ?? t('quote-breakdown__total') }}</span>
      <span>{{ formatMoney(quote.total) }}</span>
    </li>
  </ul>
</template>
