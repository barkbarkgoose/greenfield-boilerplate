import { describe, expect, it } from 'vitest'
import { DRAFT_KEY, DRAFT_MAX_AGE_DAYS, clearDraft, isEmptyDraft, loadDraft, saveDraft } from '@/utils/intakeDraft'

function memoryStorage() {
  const data = new Map<string, string>()
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key)
  }
}

const NOW = Date.UTC(2026, 9, 3)
const DAY = 86_400_000

describe('intake draft', () => {
  it('round-trips the form and selected services', () => {
    const storage = memoryStorage()
    saveDraft({ form: { vin: '1HGCM82633A004352', name: 'Pat' }, selected: { brake_pads: 2, oil_change: 1 } }, storage, NOW)
    expect(loadDraft(storage, NOW + DAY)).toEqual({
      form: { vin: '1HGCM82633A004352', name: 'Pat' },
      selected: { brake_pads: 2, oil_change: 1 }
    })
  })

  it('never stores the honeypot or unknown fields', () => {
    const storage = memoryStorage()
    const form = { name: 'Pat', website: 'spam.example', captcha_token: 'x' } as Record<string, string>
    saveDraft({ form, selected: {} }, storage, NOW)
    expect(storage.data.get(DRAFT_KEY)).not.toContain('spam.example')
    expect(storage.data.get(DRAFT_KEY)).not.toContain('captcha_token')
  })

  it('expires old drafts', () => {
    const storage = memoryStorage()
    saveDraft({ form: { name: 'Pat' }, selected: {} }, storage, NOW)
    expect(loadDraft(storage, NOW + (DRAFT_MAX_AGE_DAYS + 1) * DAY)).toBeNull()
    expect(storage.data.has(DRAFT_KEY)).toBe(false)
  })

  it('ignores corrupt or tampered data', () => {
    const storage = memoryStorage()
    storage.setItem(DRAFT_KEY, '{not json')
    expect(loadDraft(storage, NOW)).toBeNull()

    storage.setItem(
      DRAFT_KEY,
      JSON.stringify({ v: 1, savedAt: NOW, form: { name: 42, vin: 'ABC' }, selected: { brake_pads: -1, oil_change: 1.5, air_filter: 1 } })
    )
    expect(loadDraft(storage, NOW)).toEqual({ form: { vin: 'ABC' }, selected: { air_filter: 1 } })
  })

  it('works without storage', () => {
    expect(() => saveDraft({ form: {}, selected: {} }, null)).not.toThrow()
    expect(loadDraft(null)).toBeNull()
    expect(() => clearDraft(null)).not.toThrow()
  })

  it('treats untouched defaults as empty', () => {
    const defaults = { preferred_date: '2026-10-17' }
    expect(isEmptyDraft({ form: { preferred_date: '2026-10-17' }, selected: {} }, defaults)).toBe(true)
    expect(isEmptyDraft({ form: { preferred_date: '2026-10-20' }, selected: {} }, defaults)).toBe(false)
    expect(isEmptyDraft({ form: {}, selected: { oil_change: 1 } }, defaults)).toBe(false)
  })
})
