<script setup lang="ts">
import { computed } from 'vue'
import { statusOption } from '@/utils/intake'

const props = defineProps<{ status: string }>()
const option = computed(() => statusOption(props.status))
</script>

<template>
  <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset" :class="option.classes">
    {{ option.label }}
  </span>
</template>
