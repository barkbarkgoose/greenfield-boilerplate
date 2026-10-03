import { onBeforeUnmount, ref } from 'vue'
import type { PartsEstimate } from '@/types/intake'

const INTERVAL_MS = 3000
const MAX_ATTEMPTS = 40 // ~2 minutes

/**
 * Holds a request's parts estimate and polls while it's being generated.
 * `fetcher` only reads; estimates are produced server-side after booking.
 */
export function usePartsEstimate(fetcher: () => Promise<PartsEstimate | null>) {
  const estimate = ref<PartsEstimate | null>(null)
  let timer: ReturnType<typeof setTimeout> | undefined
  let attempts = 0

  function stop() {
    clearTimeout(timer)
  }

  function set(value: PartsEstimate | null) {
    estimate.value = value
    stop()
    if (value?.status === 'pending' && attempts < MAX_ATTEMPTS) {
      timer = setTimeout(poll, INTERVAL_MS)
    }
  }

  async function poll() {
    attempts += 1
    try {
      set(await fetcher())
    } catch {
      stop()
    }
  }

  function start(initial: PartsEstimate | null) {
    attempts = 0
    set(initial)
  }

  onBeforeUnmount(stop)
  return { estimate, start, stop }
}
