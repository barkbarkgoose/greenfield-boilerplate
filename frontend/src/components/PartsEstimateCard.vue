<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PartsEstimate } from '@/types/intake'
import { formatDate, formatMoney } from '@/utils/intake'
import { partsPolicy } from '@/config/business'

const props = defineProps<{
  estimate: PartsEstimate
  // Labor + fees total, to show an all-in range.
  laborTotal?: string | null
  vehicleLabel?: string
}>()

const showDetails = ref(false)

const allIn = computed(() => {
  if (props.estimate.status !== 'ready' || !props.laborTotal) return null
  const labor = Number(props.laborTotal)
  return {
    low: labor + Number(props.estimate.low ?? 0),
    typical: labor + Number(props.estimate.typical ?? 0),
    high: labor + Number(props.estimate.high ?? 0)
  }
})

function range(low?: string | number, high?: string | number) {
  if (low === undefined || high === undefined) return ''
  return Number(low) === Number(high) ? formatMoney(low) : `${formatMoney(low)}–${formatMoney(high)}`
}
</script>

<template>
  <div>
    <div v-if="estimate.status === 'pending'" class="flex items-center gap-3 text-sm text-slate-600">
      <span class="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-amber-500" aria-hidden="true" />
      Estimating parts for {{ vehicleLabel || 'your vehicle' }}…
    </div>

    <p v-else-if="estimate.status === 'unavailable'" class="text-sm text-slate-600">
      Parts will be quoted after I look up your VIN. {{ partsPolicy.short }}
    </p>

    <template v-else>
      <div class="flex items-baseline justify-between gap-3">
        <span class="text-sm text-slate-600">Parts</span>
        <span class="text-right">
          <span class="text-lg font-bold text-slate-900">{{ range(estimate.low, estimate.high) }}</span>
          <span class="block text-xs text-slate-500">typically {{ formatMoney(estimate.typical ?? 0) }}</span>
        </span>
      </div>
      <div v-if="allIn" class="mt-2 flex items-baseline justify-between gap-3 border-t border-slate-100 pt-2">
        <span class="text-sm font-semibold text-slate-900">All-in estimate</span>
        <span class="text-right">
          <span class="text-lg font-bold text-slate-900">{{ range(allIn.low, allIn.high) }}</span>
          <span class="block text-xs text-slate-500">typically {{ formatMoney(allIn.typical) }}</span>
        </span>
      </div>
      <p v-if="estimate.missing?.length" class="mt-2 text-xs text-slate-600">
        Quoted separately: {{ estimate.missing.join(', ') }}.
      </p>

      <button type="button" class="mt-3 text-sm font-medium text-amber-700 hover:text-amber-600" @click="showDetails = !showDetails">
        {{ showDetails ? 'Hide price details' : 'See price details' }}
      </button>
      <div v-if="showDetails" class="mt-3 space-y-3">
        <div v-for="service in estimate.services" :key="service.service_key">
          <p class="flex justify-between gap-3 text-sm font-medium text-slate-800">
            <span>{{ service.name }}<template v-if="service.quantity > 1"> ×{{ service.quantity }}</template></span>
            <span>{{ range(service.low, service.high) }}</span>
          </p>
          <p class="text-xs text-slate-500">
            Typically {{ formatMoney(service.typical) }} · based on {{ service.sample_count }}
            {{ service.sample_count === 1 ? 'price' : 'prices' }} for {{ service.basis }}<template v-if="service.quantity > 1">, per {{ service.unit }}</template>
          </p>
          <ul class="mt-1 space-y-0.5 text-xs text-slate-600">
            <li v-for="(example, index) in service.examples" :key="index" class="flex justify-between gap-3">
              <span class="min-w-0 truncate">
                {{ [example.part_brand, example.description].filter(Boolean).join(' · ') || 'Example' }}
                <span v-if="example.source" class="text-slate-400">({{ example.source }})</span>
              </span>
              <span class="whitespace-nowrap">{{ formatMoney(example.price) }}</span>
            </li>
          </ul>
        </div>
      </div>

      <p class="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-900">{{ partsPolicy.long }}</p>
      <p class="mt-2 text-xs text-slate-500">
        Ranges come from real parts-store prices I've collected for similar vehicles<template v-if="estimate.vehicle_type_label"> ({{ estimate.vehicle_type_label.toLowerCase() }})</template>.
        Not a quote: I'll confirm the exact parts and prices before ordering. Parts bought locally on short notice usually cost more.
        <template v-if="estimate.generated_at"> Estimated {{ formatDate(estimate.generated_at) }}.</template>
      </p>
    </template>
  </div>
</template>
