<script setup lang="ts">
// Cloudflare Turnstile captcha. Renders nothing unless VITE_TURNSTILE_SITE_KEY
// is set, matching the backend, which only checks when its secret is set.
import { onBeforeUnmount, onMounted, ref } from 'vue'

interface TurnstileApi {
  render: (el: HTMLElement, options: Record<string, unknown>) => string
  reset: (id: string) => void
  remove: (id: string) => void
}

declare global {
  interface Window {
    turnstile?: TurnstileApi
  }
}

const emit = defineEmits<{ (e: 'update:token', token: string): void }>()

const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY as string | undefined
const container = ref<HTMLElement | null>(null)
const failed = ref(false)
let widgetId: string | null = null

const SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'

function loadScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve()
  const existing = document.querySelector<HTMLScriptElement>(`script[src="${SCRIPT_SRC}"]`)
  return new Promise((resolve, reject) => {
    const script = existing ?? document.createElement('script')
    script.addEventListener('load', () => resolve())
    script.addEventListener('error', () => reject(new Error('turnstile')))
    if (!existing) {
      script.src = SCRIPT_SRC
      script.async = true
      document.head.appendChild(script)
    }
  })
}

function reset() {
  emit('update:token', '')
  if (widgetId && window.turnstile) window.turnstile.reset(widgetId)
}

defineExpose({ reset })

onMounted(async () => {
  if (!siteKey || !container.value) return
  try {
    await loadScript()
    widgetId = window.turnstile!.render(container.value, {
      sitekey: siteKey,
      callback: (token: string) => emit('update:token', token),
      'expired-callback': () => emit('update:token', ''),
      'error-callback': () => emit('update:token', '')
    })
  } catch {
    failed.value = true
  }
})

onBeforeUnmount(() => {
  if (widgetId && window.turnstile) window.turnstile.remove(widgetId)
})
</script>

<template>
  <div v-if="siteKey">
    <div ref="container" />
    <p v-if="failed" class="mt-2 text-xs text-red-300">
      The verification check couldn't load. Disable content blockers or try another browser.
    </p>
  </div>
</template>
