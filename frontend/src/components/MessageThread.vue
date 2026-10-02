<script setup lang="ts">
import { ref } from 'vue'
import type { RequestMessage } from '@/types/garage'
import { formatDateTime } from '@/utils/intake'

const props = defineProps<{
  messages: RequestMessage[]
  // Whose side is "me": staff messages render on the right for the mechanic.
  viewer: 'staff' | 'customer'
  send: (body: string) => Promise<void>
  placeholder?: string
  hint?: string
}>()

const draft = ref('')
const sending = ref(false)
const error = ref('')

function isMine(message: RequestMessage) {
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
    error.value = "Your message couldn't be sent. Please try again."
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <div>
    <p v-if="messages.length === 0" class="rounded-xl bg-slate-50 p-4 text-sm text-slate-500">
      No messages yet.
    </p>
    <ol v-else class="space-y-3">
      <li v-for="message in messages" :key="message.id" class="flex" :class="isMine(message) ? 'justify-end' : 'justify-start'">
        <div
          class="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm"
          :class="isMine(message) ? 'rounded-br-md bg-slate-900 text-white' : 'rounded-bl-md bg-slate-100 text-slate-800'"
        >
          <p class="whitespace-pre-wrap break-words">{{ message.body }}</p>
          <p class="mt-1 text-[11px]" :class="isMine(message) ? 'text-slate-400' : 'text-slate-500'">
            {{ isMine(message) ? 'You' : message.author_name }} · {{ formatDateTime(message.created_at) }}
          </p>
        </div>
      </li>
    </ol>

    <form class="mt-4" @submit.prevent="submit">
      <label for="message-draft" class="sr-only">Message</label>
      <textarea
        id="message-draft"
        v-model="draft"
        rows="3"
        maxlength="4000"
        :placeholder="placeholder ?? 'Write a message…'"
        class="block w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm shadow-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-400/40"
        @keydown.meta.enter="submit"
        @keydown.ctrl.enter="submit"
      />
      <div class="mt-2 flex items-center justify-between gap-3">
        <p class="text-xs text-slate-500">{{ error || hint }}</p>
        <button
          type="submit"
          :disabled="sending || !draft.trim()"
          class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {{ sending ? 'Sending…' : 'Send' }}
        </button>
      </div>
    </form>
  </div>
</template>
