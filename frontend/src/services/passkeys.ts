// Passkeys (WebAuthn) for accounts that require one. The browser library talks
// to the password manager (Bitwarden, iCloud Keychain, Google, a security key);
// the server checks the result. See backend/apps/users/passkeys.py.
import { startAuthentication, startRegistration } from '@simplewebauthn/browser'
import type {
  PublicKeyCredentialCreationOptionsJSON,
  PublicKeyCredentialRequestOptionsJSON
} from '@simplewebauthn/browser'
import api from '@/services/api'
import type { LoginResponse, User } from '@/types/auth'

export interface Passkey {
  id: number
  name: string
  created_at: string
  last_used_at: string | null
}

export interface PasskeyChallenge<T> {
  options: T
  challenge_token: string
}

export type PasskeyLoginChallenge = PasskeyChallenge<PublicKeyCredentialRequestOptionsJSON>

/** Ask the password manager for the passkey, then finish signing in. */
export async function signInWithPasskey(challenge: PasskeyLoginChallenge): Promise<LoginResponse & { user: User }> {
  const credential = await startAuthentication({ optionsJSON: challenge.options })
  const { data } = await api.post('/api/v1/auth/passkeys/login/', {
    challenge_token: challenge.challenge_token,
    credential
  })
  return data
}

export async function listPasskeys(): Promise<{ required: boolean; passkeys: Passkey[] }> {
  return (await api.get('/api/v1/auth/passkeys/')).data
}

/** Create a passkey in the password manager and save it. Returns a fresh session. */
export async function createPasskey(name: string): Promise<{ passkey: Passkey; access: string; refresh: string }> {
  const { data: challenge } = await api.post<PasskeyChallenge<PublicKeyCredentialCreationOptionsJSON>>(
    '/api/v1/auth/passkeys/register/options/'
  )
  const credential = await startRegistration({ optionsJSON: challenge.options })
  const { data } = await api.post('/api/v1/auth/passkeys/register/', {
    challenge_token: challenge.challenge_token,
    credential,
    name
  })
  return data
}

export async function deletePasskey(id: number): Promise<void> {
  await api.delete(`/api/v1/auth/passkeys/${id}/`)
}

/** True when the person closed or cancelled the passkey prompt. */
export function isPasskeyCancelled(error: unknown): boolean {
  return error instanceof Error && (error.name === 'NotAllowedError' || error.name === 'AbortError')
}
