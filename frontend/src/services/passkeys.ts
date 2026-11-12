/**
 * Passkey API calls. Each WebAuthn ceremony is a begin request (options for the
 * browser plus a one-time challenge id), the browser prompt, then a finish request.
 */

import {
  browserSupportsWebAuthn,
  startAuthentication,
  startRegistration
} from '@simplewebauthn/browser'
import type {
  PublicKeyCredentialCreationOptionsJSON,
  PublicKeyCredentialRequestOptionsJSON
} from '@simplewebauthn/browser'
import api from '@/services/api'
import type { LoginResponse, Passkey } from '@/types/auth'
import { firstError } from '@/utils/apiErrors'

interface Begin<Options> {
  challenge_id: string
  options: Options
}

const BASE = '/api/v1/auth/passkeys'

/** Passkeys need WebAuthn and a secure context (https, or http://localhost). */
export function passkeysSupported(): boolean {
  return browserSupportsWebAuthn()
}

export async function signInWithPasskey(): Promise<LoginResponse> {
  const begin = await api.post<Begin<PublicKeyCredentialRequestOptionsJSON>>(`${BASE}/login/begin/`)
  const credential = await startAuthentication({ optionsJSON: begin.data.options })
  const response = await api.post<LoginResponse>(`${BASE}/login/finish/`, {
    challenge_id: begin.data.challenge_id,
    credential
  })
  return response.data
}

export async function createPasskey(name = ''): Promise<Passkey> {
  const begin = await api.post<Begin<PublicKeyCredentialCreationOptionsJSON>>(`${BASE}/register/begin/`)
  const credential = await startRegistration({ optionsJSON: begin.data.options })
  const response = await api.post<Passkey>(`${BASE}/register/finish/`, {
    challenge_id: begin.data.challenge_id,
    credential,
    name
  })
  return response.data
}

export async function listPasskeys(): Promise<Passkey[]> {
  return (await api.get<Passkey[]>(`${BASE}/`)).data
}

export async function deletePasskey(id: number): Promise<void> {
  await api.delete(`${BASE}/${id}/`)
}

/** A message for a failed passkey step, or null when the user cancelled the prompt. */
export function passkeyErrorMessage(error: unknown): string | null {
  if (error && typeof error === 'object' && 'response' in error) {
    const data = (error as { response?: { data?: unknown } }).response?.data
    return firstError(data) || 'Something went wrong. Please try again.'
  }
  const name = error instanceof Error ? error.name : ''
  if (name === 'NotAllowedError' || name === 'AbortError') return null
  if (name === 'InvalidStateError') return 'This device already has a passkey for your account.'
  if (name === 'SecurityError') return 'Passkeys need a secure (https) connection to this site.'
  return 'Your browser could not use a passkey. Please try again.'
}
