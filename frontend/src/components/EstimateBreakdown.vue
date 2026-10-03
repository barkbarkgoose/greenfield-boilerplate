<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { Estimate } from '@/types/intake'
import { formatMoney } from '@/utils/intake'

defineProps<{ estimate: Estimate; totalLabel?: string }>()
const { t } = useI18n()
</script>

<template>
  <ul class="space-y-1.5 text-sm">
    <li v-for="item in estimate.line_items" :key="item.key" class="flex justify-between gap-3 text-slate-600">
      <span>{{ item.name }}<template v-if="item.quantity > 1"> ×{{ item.quantity }}</template></span>
      <span>{{ item.quote_required ? t('estimate-breakdown__quote-pending') : formatMoney(item.amount) }}</span>
    </li>
    <li v-for="d in estimate.discounts" :key="d.key" class="flex justify-between gap-3 text-emerald-700">
      <span>{{ d.name }}<template v-if="d.units > 1"> ×{{ d.units }}</template></span>
      <span>−{{ formatMoney(d.amount) }}</span>
    </li>
    <li class="flex justify-between gap-3 text-slate-600">
      <span>{{ t('estimate-breakdown__line--service-call') }}</span><span>{{ formatMoney(estimate.service_call_fee) }}</span>
    </li>
    <li v-if="Number(estimate.emergency_fee) > 0" class="flex justify-between gap-3 text-red-700">
      <span>{{ t('estimate-breakdown__line--emergency-fee') }}</span><span>{{ formatMoney(estimate.emergency_fee) }}</span>
    </li>
    <li class="flex justify-between gap-3 border-t border-slate-100 pt-2 font-semibold text-slate-900">
      <span>{{ totalLabel ?? t('estimate-breakdown__total') }}</span>
      <span>{{ formatMoney(estimate.total) }}<template v-if="estimate.needs_custom_quote">+</template></span>
    </li>
  </ul>
</template>
