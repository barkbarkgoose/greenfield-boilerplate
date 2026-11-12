import { describe, expect, it } from 'vitest'
import { safeRedirect } from '../redirect'

describe('safeRedirect', () => {
  it('keeps paths on this site', () => {
    expect(safeRedirect('/settings?tab=1')).toBe('/settings?tab=1')
    expect(safeRedirect('/django-admin/')).toBe('/django-admin/')
  })

  it('rejects other sites and junk', () => {
    expect(safeRedirect('https://evil.example/')).toBeNull()
    expect(safeRedirect('//evil.example/')).toBeNull()
    expect(safeRedirect('/\\evil.example/')).toBeNull()
    expect(safeRedirect(['/settings'])).toBeNull()
    expect(safeRedirect(undefined)).toBeNull()
  })
})
