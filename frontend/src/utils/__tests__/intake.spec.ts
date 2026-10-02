import { describe, expect, it } from 'vitest'
import { VIN_PATTERN, formatMoney, normalizeVin } from '@/utils/intake'

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
