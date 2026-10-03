// Keeps an unsubmitted booking form in the browser so a refresh, a trip to
// another page, or closing the tab doesn't lose it. It lives in localStorage
// on this device only, is dropped once the request is sent, and expires after
// DRAFT_MAX_AGE_DAYS so an old half-filled form doesn't linger.

export const DRAFT_KEY = 'intake-draft'
const DRAFT_VERSION = 1
export const DRAFT_MAX_AGE_DAYS = 14

// Every text field on the form except the honeypot and captcha.
export const DRAFT_FIELDS = [
  'name',
  'phone',
  'email',
  'service_address',
  'vin',
  'vehicle_year',
  'vehicle_make',
  'vehicle_model',
  'vehicle_type',
  'other_description',
  'preferred_date',
  'notes'
] as const

export type DraftField = (typeof DRAFT_FIELDS)[number]

export interface IntakeDraft {
  form: Partial<Record<DraftField, string>>
  // Service key -> quantity.
  selected: Record<string, number>
}

type DraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

function defaultStorage(): DraftStorage | null {
  try {
    return globalThis.localStorage ?? null
  } catch {
    // Storage can throw in private windows or with site data blocked.
    return null
  }
}

export function isEmptyDraft(draft: IntakeDraft, defaults: Partial<Record<DraftField, string>> = {}): boolean {
  const formTouched = DRAFT_FIELDS.some((field) => {
    const value = draft.form[field] ?? ''
    return value !== '' && value !== (defaults[field] ?? '')
  })
  return !formTouched && Object.keys(draft.selected).length === 0
}

export function saveDraft(draft: IntakeDraft, storage = defaultStorage(), now = Date.now()): void {
  if (!storage) return
  try {
    const form: Partial<Record<DraftField, string>> = {}
    for (const field of DRAFT_FIELDS) {
      const value = draft.form[field]
      if (typeof value === 'string' && value !== '') form[field] = value
    }
    storage.setItem(DRAFT_KEY, JSON.stringify({ v: DRAFT_VERSION, savedAt: now, form, selected: draft.selected }))
  } catch {
    // Full or blocked storage: the form still works, it just won't be saved.
  }
}

export function clearDraft(storage = defaultStorage()): void {
  try {
    storage?.removeItem(DRAFT_KEY)
  } catch {
    // Nothing to do.
  }
}

/** The saved draft, or null when there is none, it's expired or unreadable. */
export function loadDraft(storage = defaultStorage(), now = Date.now()): IntakeDraft | null {
  if (!storage) return null
  let raw: unknown
  try {
    const text = storage.getItem(DRAFT_KEY)
    if (!text) return null
    raw = JSON.parse(text)
  } catch {
    clearDraft(storage)
    return null
  }
  if (!raw || typeof raw !== 'object') return null
  const data = raw as { v?: unknown; savedAt?: unknown; form?: unknown; selected?: unknown }
  const age = now - Number(data.savedAt)
  if (data.v !== DRAFT_VERSION || !Number.isFinite(age) || age > DRAFT_MAX_AGE_DAYS * 86_400_000) {
    clearDraft(storage)
    return null
  }

  const form: Partial<Record<DraftField, string>> = {}
  if (data.form && typeof data.form === 'object') {
    for (const field of DRAFT_FIELDS) {
      const value = (data.form as Record<string, unknown>)[field]
      if (typeof value === 'string') form[field] = value.slice(0, 4000)
    }
  }
  const selected: Record<string, number> = {}
  if (data.selected && typeof data.selected === 'object') {
    for (const [key, quantity] of Object.entries(data.selected as Record<string, unknown>)) {
      if (Number.isInteger(quantity) && (quantity as number) > 0) selected[key] = quantity as number
    }
  }
  return { form, selected }
}
