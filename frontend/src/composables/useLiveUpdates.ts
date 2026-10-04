import { onBeforeUnmount, onMounted } from 'vue'
import type { OrderMessage, OrderUpdates } from '@/types/account'

// How often an open request page checks for new messages and changes. Polling
// keeps this simple on a plain Django server; docs/realtime-messaging.md covers
// moving to pushed updates (SSE or WebSockets) if this ever needs to be instant.
export const POLL_INTERVAL_MS = 10_000
const MAX_BACKOFF_MS = 120_000

/** Append messages that aren't already in the thread, oldest first. */
export function mergeMessages(existing: OrderMessage[], incoming: OrderMessage[]): OrderMessage[] {
  const known = new Set(existing.map((message) => message.id))
  const added = incoming.filter((message) => !known.has(message.id))
  if (added.length === 0) return existing
  return [...existing, ...added].sort((a, b) => a.id - b.id)
}

export function lastMessageId(messages: OrderMessage[]): number {
  return messages.reduce((max, message) => Math.max(max, message.id), 0)
}

/**
 * Polls a request page for new messages while the tab is visible, and calls
 * `onChanged` when something else about the request changed (status,
 * appointment, invoice...) so the page can reload it.
 */
export function useLiveUpdates(options: {
  poll: (afterId: number) => Promise<OrderUpdates>
  messages: () => OrderMessage[] | undefined
  onMessages: (messages: OrderMessage[]) => void
  onChanged: () => void | Promise<void>
}) {
  let timer: ReturnType<typeof setTimeout> | undefined
  let updatedAt: string | null = null
  let delay = POLL_INTERVAL_MS
  let running = false
  let inFlight = false

  function schedule(ms = delay) {
    clearTimeout(timer)
    if (running) timer = setTimeout(tick, ms)
  }

  async function tick() {
    const current = options.messages()
    if (!running || current === undefined) return
    // Hidden tabs don't poll; becoming visible again checks right away.
    if (document.visibilityState === 'hidden' || inFlight) return schedule()
    inFlight = true
    try {
      const result = await options.poll(lastMessageId(current))
      if (result.messages.length) options.onMessages(result.messages)
      if (updatedAt && result.updated_at !== updatedAt) {
        updatedAt = result.updated_at
        await options.onChanged()
      }
      updatedAt = result.updated_at
      delay = POLL_INTERVAL_MS
    } catch {
      // Back off while the server is unreachable or rate limiting.
      delay = Math.min(delay * 2, MAX_BACKOFF_MS)
    } finally {
      inFlight = false
      schedule()
    }
  }

  function handleVisibility() {
    if (document.visibilityState === 'visible') schedule(0)
  }

  /** Begin polling. `since` is the request's updated_at as already loaded. */
  function start(since: string) {
    updatedAt = since
    running = true
    delay = POLL_INTERVAL_MS
    schedule()
  }

  /** Record a change this page made itself, so it doesn't trigger a reload. */
  function acknowledge(since: string) {
    updatedAt = since
  }

  function stop() {
    running = false
    clearTimeout(timer)
  }

  onMounted(() => document.addEventListener('visibilitychange', handleVisibility))
  onBeforeUnmount(() => {
    stop()
    document.removeEventListener('visibilitychange', handleVisibility)
  })

  return { start, stop, acknowledge }
}
