<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { statusOption } from '@/utils/format'

const props = defineProps<{ status: string }>()
const { t } = useI18n()
const option = computed(() => statusOption(props.status))
</script>

<template>
  <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset" :class="option.classes">
    {{ t(`request-status__label--${option.value}`) }}
  </span>
</template>
