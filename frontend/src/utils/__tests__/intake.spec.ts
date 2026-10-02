import { describe, expect, it } from 'vitest'
import {
  VIN_PATTERN,
  formatDate,
  formatMoney,
  fromDateTimeLocal,
  normalizeVin,
  servicesLabel,
  toDateTimeLocal
} from '@/utils/intake'

describe('normalizeVin', () => {
  it('uppercases and strips spaces and dashes', () => {
    expect(normalizeVin(' 1hgcm-82633 a004352 ')).toBe('1HGCM82633A004352')
  })
})

describe('VIN_PATTERN', () => {
  it('accepts a 17-character VIN', () => {
    expect(VIN_PATTERN.test('1HGCM82633A004352')).toBe(true)
  })

  it('rejects the wrong length and the letters I, O and Q', () => {
    expect(VIN_PATTERN.test('1HGCM82633A00435')).toBe(false)
    expect(VIN_PATTERN.test('1HGCM82633A00435O')).toBe(false)
    expect(VIN_PATTERN.test('IHGCM82633A004352')).toBe(false)
  })
})

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

describe('servicesLabel', () => {
  it('joins names and marks quantities', () => {
    expect(
      servicesLabel([
        { name: 'Brake pads', quantity: 2 },
        { name: 'Oil change', quantity: 1 }
      ])
    ).toBe('Brake pads ×2, Oil change')
  })
})
