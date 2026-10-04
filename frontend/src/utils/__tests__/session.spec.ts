import { describe, expect, it } from 'vitest'
import { RENEW_MARGIN_SECONDS, sessionAction } from '@/utils/session'

function tokenExpiringIn(seconds: number): string {
  const payload = { exp: Math.floor(Date.now() / 1000) + seconds }
  const encode = (value: object) => btoa(JSON.stringify(value)).replace(/=+$/, '')
  return `${encode({ alg: 'HS256' })}.${encode(payload)}.signature`
}

describe('session renewal', () => {
  const freshAccess = tokenExpiringIn(600)
  const expiringAccess = tokenExpiringIn(RENEW_MARGIN_SECONDS - 5)
  const liveRefresh = tokenExpiringIn(8 * 3600)
  const deadRefresh = tokenExpiringIn(-60)

  it('uses an access token that is good for a while', () => {
    expect(sessionAction(freshAccess, liveRefresh)).toBe('use')
  })

  it('renews shortly before the access token expires', () => {
    expect(sessionAction(expiringAccess, liveRefresh)).toBe('renew')
    expect(sessionAction(null, liveRefresh)).toBe('renew')
  })

  it('ends the session once the refresh token is gone or expired', () => {
    expect(sessionAction(expiringAccess, deadRefresh)).toBe('ended')
    expect(sessionAction(expiringAccess, null)).toBe('ended')
    expect(sessionAction(null, null)).toBe('ended')
  })
})
