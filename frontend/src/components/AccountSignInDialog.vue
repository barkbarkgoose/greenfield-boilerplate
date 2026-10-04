<script setup lang="ts">
// Shown when a guest taps "My orders": explains what an account gives them and
// sends them to create one or sign in, then back to their orders.
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const dialog = ref<HTMLDialogElement | null>(null)
const orders = { redirect: '/account' }

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
    class="account-dialog m-auto w-[calc(100%-2rem)] max-w-md rounded-3xl bg-white p-0 text-stone-900 shadow-2xl backdrop:bg-stone-950/60"
    aria-labelledby="account-dialog-title"
    @click="handleClick"
  >
    <div class="p-6 sm:p-8">
      <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-lime-100 text-lime-800">
        <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
        </svg>
      </div>
      <h2 id="account-dialog-title" class="mt-4 text-xl font-bold">{{ t('account-dialog__title') }}</h2>
      <p class="mt-2 text-sm text-stone-600">{{ t('account-dialog__body') }}</p>
      <ul class="mt-4 space-y-1.5 text-sm text-stone-700">
        <li v-for="n in 3" :key="n" class="flex gap-2">
          <span class="text-emerald-600" aria-hidden="true">✓</span>{{ t(`account-dialog__perk--${n}`) }}
        </li>
      </ul>

      <div class="mt-6 flex flex-col gap-2">
        <router-link
          :to="{ name: 'register', query: orders }"
          class="rounded-xl bg-lime-500 px-4 py-3 text-center font-semibold text-stone-900 hover:bg-lime-400"
          @click="close"
        >
          {{ t('account-dialog__register') }}
        </router-link>
        <router-link
          :to="{ name: 'login', query: orders }"
          class="rounded-xl px-4 py-3 text-center font-semibold text-stone-700 ring-1 ring-stone-300 hover:bg-stone-50"
          @click="close"
        >
          {{ t('account-dialog__sign-in') }}
        </router-link>
      </div>
      <p class="mt-4 text-xs text-stone-500">{{ t('account-dialog__note') }}</p>
      <button type="button" class="mt-4 w-full text-center text-sm font-medium text-stone-500 hover:text-stone-800" @click="close">
        {{ t('account-dialog__dismiss') }}
      </button>
    </div>
  </dialog>
</template>
