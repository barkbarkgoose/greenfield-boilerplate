<script setup lang="ts">
// Shown when a guest taps "My garage": explains what the garage is and sends
// them to create an account or sign in, then back to the garage.
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const dialog = ref<HTMLDialogElement | null>(null)
const garage = { redirect: '/account' }

function open() {
  dialog.value?.showModal()
}

function close() {
  dialog.value?.close()
}

// Clicks on the backdrop land on the <dialog> element itself.
function handleClick(event: MouseEvent) {
  if (event.target === dialog.value) close()
}

defineExpose({ open, close })
</script>

<template>
  <dialog
    ref="dialog"
    class="garage-dialog m-auto w-[calc(100%-2rem)] max-w-md rounded-3xl bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-950/60"
    aria-labelledby="garage-dialog-title"
    @click="handleClick"
  >
    <div class="p-6 sm:p-8">
      <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-100 text-amber-700">
        <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 10.5L12 4l9 6.5V20a1 1 0 01-1 1H4a1 1 0 01-1-1v-9.5zM7 21v-7h10v7M7 17.5h10" />
        </svg>
      </div>
      <h2 id="garage-dialog-title" class="mt-4 text-xl font-bold">{{ t('garage-dialog__title') }}</h2>
      <p class="mt-2 text-sm text-slate-600">{{ t('garage-dialog__body') }}</p>
      <ul class="mt-4 space-y-1.5 text-sm text-slate-700">
        <li v-for="n in 3" :key="n" class="flex gap-2">
          <span class="text-emerald-600" aria-hidden="true">✓</span>{{ t(`garage-dialog__perk--${n}`) }}
        </li>
      </ul>

      <div class="mt-6 flex flex-col gap-2">
        <router-link
          :to="{ name: 'register', query: garage }"
          class="rounded-xl bg-amber-400 px-4 py-3 text-center font-semibold text-slate-900 hover:bg-amber-300"
          @click="close"
        >
          {{ t('garage-dialog__register') }}
        </router-link>
        <router-link
          :to="{ name: 'login', query: garage }"
          class="rounded-xl px-4 py-3 text-center font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50"
          @click="close"
        >
          {{ t('garage-dialog__sign-in') }}
        </router-link>
      </div>
      <p class="mt-4 text-xs text-slate-500">{{ t('garage-dialog__note') }}</p>
      <button type="button" class="mt-4 w-full text-center text-sm font-medium text-slate-500 hover:text-slate-800" @click="close">
        {{ t('garage-dialog__dismiss') }}
      </button>
    </div>
  </dialog>
</template>
