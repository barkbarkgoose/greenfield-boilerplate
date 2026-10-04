<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { OrderMessage } from '@/types/account'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{
  messages: OrderMessage[]
  // Whose side is "me": staff messages render on the right for staff.
  viewer: 'staff' | 'customer'
  send: (body: string) => Promise<void>
  placeholder?: string
  hint?: string
}>()

const { t } = useI18n()
const draft = ref('')
const sending = ref(false)
const error = ref('')

function isMine(message: OrderMessage) {
  return message.from_staff === (props.viewer === 'staff')
}

async function submit() {
  const body = draft.value.trim()
  if (!body) return
  sending.value = true
  error.value = ''
  try {
    await props.send(body)
    draft.value = ''
  } catch {
    error.value = t('message-thread__error')
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <div>
    <p v-if="messages.length === 0" class="rounded-xl bg-stone-50 p-4 text-sm text-stone-500">
      {{ t('message-thread__empty') }}
    </p>
    <ol v-else class="space-y-3">
      <li v-for="message in messages" :key="message.id" class="flex" :class="isMine(message) ? 'justify-end' : 'justify-start'">
        <div
          class="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm"
          :class="isMine(message) ? 'rounded-br-md bg-stone-900 text-white' : 'rounded-bl-md bg-stone-100 text-stone-800'"
        >
          <p class="whitespace-pre-wrap break-words">{{ message.body }}</p>
          <p class="mt-1 text-[11px]" :class="isMine(message) ? 'text-stone-400' : 'text-stone-500'">
            {{ isMine(message) ? t('message-thread__author--you') : message.author_name }} · {{ formatDateTime(message.created_at) }}
          </p>
        </div>
      </li>
    </ol>

    <form class="mt-4" @submit.prevent="submit">
      <label for="message-draft" class="sr-only">{{ t('message-thread__input-label') }}</label>
      <textarea
        id="message-draft"
        v-model="draft"
        rows="3"
        maxlength="4000"
        :placeholder="placeholder ?? t('message-thread__input-placeholder')"
        class="block w-full rounded-xl border border-stone-300 px-3 py-2.5 text-sm shadow-sm focus:border-lime-500 focus:outline-none focus:ring-2 focus:ring-lime-400/40"
        @keydown.meta.enter="submit"
        @keydown.ctrl.enter="submit"
      />
      <div class="mt-2 flex items-center justify-between gap-3">
        <p class="text-xs text-stone-500">{{ error || hint }}</p>
        <button
          type="submit"
          :disabled="sending || !draft.trim()"
          class="rounded-lg bg-stone-900 px-4 py-2 text-sm font-semibold text-white hover:bg-stone-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {{ sending ? t('message-thread__send--sending') : t('message-thread__send') }}
        </button>
      </div>
    </form>
  </div>
</template>
