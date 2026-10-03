<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PartsEstimate } from '@/types/intake'
import { formatDate, formatMoney } from '@/utils/intake'

const props = defineProps<{
  estimate: PartsEstimate
  // Labor + fees total, to show an all-in range.
  laborTotal?: string | null
  vehicleLabel?: string
}>()

const showParts = ref(false)

const allIn = computed(() => {
  if (props.estimate.status !== 'ready' || !props.laborTotal) return null
  const labor = Number(props.laborTotal)
  return { low: labor + Number(props.estimate.low ?? 0), high: labor + Number(props.estimate.high ?? 0) }
})

function range(low?: string, high?: string) {
  if (!low || !high) return ''
  return low === high ? formatMoney(low) : `${formatMoney(low)}–${formatMoney(high)}`
}

const confidenceLabel = computed(
  () => ({ low: 'Rough guess', medium: 'Typical range', high: 'Good estimate' })[props.estimate.confidence ?? 'low']
)
</script>

<template>
  <div>
    <div v-if="estimate.status === 'pending'" class="flex items-center gap-3 text-sm text-slate-600">
      <span class="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-amber-500" aria-hidden="true" />
      Estimating parts for {{ vehicleLabel || 'your vehicle' }}…
    </div>

    <p v-else-if="estimate.status === 'unavailable'" class="text-sm text-slate-600">
      Parts will be quoted after I look up your VIN.
    </p>

    <template v-else>
      <div class="flex items-baseline justify-between gap-3">
        <span class="text-sm text-slate-600">Parts</span>
        <span class="text-lg font-bold text-slate-900">{{ range(estimate.low, estimate.high) }}</span>
      </div>
      <div v-if="allIn" class="mt-1 flex items-baseline justify-between gap-3 border-t border-slate-100 pt-2">
        <span class="text-sm font-semibold text-slate-900">All-in estimate</span>
        <span class="text-lg font-bold text-slate-900">{{ range(String(allIn.low), String(allIn.high)) }}</span>
      </div>

      <button type="button" class="mt-3 text-sm font-medium text-amber-700 hover:text-amber-600" @click="showParts = !showParts">
        {{ showParts ? 'Hide parts list' : 'See parts list' }}
      </button>
      <div v-if="showParts" class="mt-3 space-y-3">
        <div v-for="service in estimate.services" :key="service.service_key">
          <p class="flex justify-between gap-3 text-sm font-medium text-slate-800">
            <span>{{ service.name }}<template v-if="service.quantity > 1"> ×{{ service.quantity }}</template></span>
            <span>{{ range(service.low, service.high) }}</span>
          </p>
          <ul class="mt-1 space-y-0.5 text-xs text-slate-600">
            <li v-for="part in service.parts" :key="part.name" class="flex justify-between gap-3">
              <span>{{ part.quantity > 1 ? `${part.quantity} × ` : '' }}{{ part.name }}</span>
              <span class="whitespace-nowrap">{{ range(part.unit_low, part.unit_high) }}{{ part.quantity > 1 ? ' ea' : '' }}</span>
            </li>
          </ul>
          <p v-if="service.notes" class="mt-1 text-xs italic text-slate-500">{{ service.notes }}</p>
        </div>
        <p v-if="estimate.assumptions" class="text-xs text-slate-500">Assumed: {{ estimate.assumptions }}</p>
      </div>

      <p class="mt-3 text-xs text-slate-500">
        {{ confidenceLabel }}: an AI estimate of typical retail prices (economy to premium), not a quote.
        I'll confirm exact parts and prices before ordering. Parts bought locally on short notice usually cost more.
        <template v-if="estimate.generated_at"> Estimated {{ formatDate(estimate.generated_at) }}.</template>
      </p>
    </template>
  </div>
</template>
