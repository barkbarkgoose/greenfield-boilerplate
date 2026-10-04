import { describe, expect, it } from 'vitest'
import {
  cubicYards,
  formatDate,
  formatMoney,
  fromDateTimeLocal,
  isDeliveryDay,
  itemsLabel,
  nextDeliveryDate,
  toDateTimeLocal
} from '@/utils/format'

const MON_TO_SAT = [0, 1, 2, 3, 4, 5]

describe('formatMoney', () => {
  it('drops cents on whole dollars', () => {
    expect(formatMoney('245.00')).toBe('$245')
  })

  it('keeps cents otherwise', () => {
    expect(formatMoney('12.50')).toBe('$12.50')
  })
})

describe('date helpers', () => {
  it('formats a date-only value without shifting the day', () => {
    expect(formatDate('2026-10-16')).toContain('Oct 16')
  })

  it('round-trips datetime-local values through ISO', () => {
    const local = '2026-10-16T09:30'
    expect(toDateTimeLocal(fromDateTimeLocal(local))).toBe(local)
    expect(fromDateTimeLocal('')).toBeNull()
  })
})

describe('delivery days', () => {
  it('uses Monday = 0 like the backend', () => {
    expect(isDeliveryDay('2026-10-04', MON_TO_SAT)).toBe(false) // Sunday
    expect(isDeliveryDay('2026-10-05', MON_TO_SAT)).toBe(true) // Monday
    expect(isDeliveryDay('2026-10-10', MON_TO_SAT)).toBe(true) // Saturday
  })

  it('skips days the trucks are off', () => {
    const day = nextDeliveryDate(3, MON_TO_SAT)
    expect(isDeliveryDay(day, MON_TO_SAT)).toBe(true)
  })
})

describe('itemsLabel', () => {
  it('joins names with yards', () => {
    expect(
      itemsLabel([
        { name: 'Screened topsoil', quantity: 10 },
        { name: 'Compost', quantity: 3 }
      ])
    ).toBe('Screened topsoil 10 yd, Compost 3 yd')
  })
})

describe('cubicYards', () => {
  it('rounds up to whole yards', () => {
    // 20 x 10 ft at 4 in = 66.7 cu ft = 2.47 yd -> 3
    expect(cubicYards(20, 10, 4)).toBe(3)
    expect(cubicYards(27, 12, 12)).toBe(12)
  })

  it('is zero until every dimension is filled in', () => {
    expect(cubicYards(20, 0, 4)).toBe(0)
    expect(cubicYards(Number.NaN, 10, 4)).toBe(0)
  })
})
