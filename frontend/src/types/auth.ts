export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  name: string
}

export interface LoginResponse {
  access: string
  refresh: string
  user?: User
  // This session can only save a passkey (see the passkey setup page).
  passkey_setup_required?: boolean
}

// Returned instead of tokens when the account requires a passkey.
export interface PasskeyStepResponse {
  passkey_required: true
  options: import('@simplewebauthn/browser').PublicKeyCredentialRequestOptionsJSON
  challenge_token: string
}

export interface RegisterResponse {
  id: number
  email: string
  name: string
  is_staff?: boolean
  token: string
  refresh?: string
}

export interface User {
  id: number
  email: string
  name: string
  is_staff?: boolean
  passkey_required?: boolean
}

export interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
}

export interface LoginCredentials {
  email: string
  password: string
}
