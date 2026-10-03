import { describe, expect, it } from 'vitest'
import { lastMessageId, mergeMessages } from '@/composables/useLiveUpdates'
import type { RequestMessage } from '@/types/garage'

function message(id: number): RequestMessage {
  return { id, body: `#${id}`, from_staff: true, author_name: 'Mechanic', created_at: '2026-10-03T12:00:00Z' }
}

describe('live updates', () => {
  it('appends only new messages, in order', () => {
    const merged = mergeMessages([message(1), message(3)], [message(3), message(2), message(4)])
    expect(merged.map((m) => m.id)).toEqual([1, 2, 3, 4])
  })

  it('keeps the same array when nothing is new', () => {
    const existing = [message(1)]
    expect(mergeMessages(existing, [message(1)])).toBe(existing)
  })

  it('polls after the newest message', () => {
    expect(lastMessageId([])).toBe(0)
    expect(lastMessageId([message(5), message(2)])).toBe(5)
  })
})
