/**
 * Keeps the sign-in alive: the access token is short-lived (15 minutes for
 * staff, 60 for customers) and is renewed with the refresh token just before
 * it expires. When the refresh token runs out (8 hours for staff, 7 days for
 * customers) or the server refuses it (password changed, account disabled),
 * the session is cleared and the person signs in again.
 *
 * Shared by the Axios instance and the router guard. Concurrent callers share
 * one renewal request.
 */
import axios from 'axios'
import { API_BASE_URL } from '@/services/apiBase'
import { REFRESH_KEY, TOKEN_KEY, clearStoredAuth } from '@/utils/authStorage'
import { isTokenExpired } from '@/utils/jwt'

// Renew this many seconds before the access token expires.
export const RENEW_MARGIN_SECONDS = 30

let renewing: Promise<string | null> | null = null

/** What to do with the stored tokens: use the access token, renew it, or give up. */
export function sessionAction(access: string | null, refresh: string | null): 'use' | 'renew' | 'ended' {
  if (access && !isTokenExpired(access, RENEW_MARGIN_SECONDS)) return 'use'
  if (refresh && !isTokenExpired(refresh)) return 'renew'
  return 'ended'
}

async function renew(refresh: string): Promise<string | null> {
  try {
    const { data } = await axios.post<{ access: string }>(`${API_BASE_URL}/api/v1/auth/refresh/`, { refresh })
    localStorage.setItem(TOKEN_KEY, data.access)
    return data.access
  } catch (error) {
    // Refused: the session is over. Network trouble: keep it and let the
    // request fail normally, so a dropped connection doesn't sign anyone out.
    if (axios.isAxiosError(error) && error.response && error.response.status < 500) {
      clearStoredAuth()
      return null
    }
    return localStorage.getItem(TOKEN_KEY)
  }
}

/** A usable access token, renewing it first if needed; null when signed out. */
export async function validAccessToken(): Promise<string | null> {
  const access = localStorage.getItem(TOKEN_KEY)
  const refresh = localStorage.getItem(REFRESH_KEY)
  const action = sessionAction(access, refresh)
  if (action === 'use') return access
  if (action === 'ended') {
    if (access || refresh) clearStoredAuth()
    return null
  }
  renewing ??= renew(refresh!).finally(() => {
    renewing = null
  })
  return renewing
}
