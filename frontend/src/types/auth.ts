export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  name: string
  organization_name?: string
}

/** What to ask after sign-in: staff must add a passkey, others are offered one. */
export type PasskeySetup = 'required' | 'offer' | null

export interface LoginResponse {
  access: string
  refresh: string
  user?: User
  passkey_setup?: PasskeySetup
}

export interface AuthConfig {
  allow_registration: boolean
  require_login: boolean
}

export interface Passkey {
  id: number
  name: string
  created_at: string
  last_used_at: string | null
  /** synced by a password manager or platform account rather than bound to one device */
  backed_up: boolean
}

export interface RegisterResponse {
  id: number
  email: string
  name: string
  organization: {
    id: number
    name: string
  } | null
  token: string
}

export interface ApiKeyStatus {
  is_configured: boolean
  preview: string
}

export interface UserSettings {
  theme_colors?: Record<string, string>
  default_view?: string
  default_ai_provider?: string
  api_keys_status?: Record<string, ApiKeyStatus>
  skip_passkey_offer?: boolean
}

export interface UserSettingsUpdate {
  theme_colors?: Record<string, string>
  default_view?: string
  default_ai_provider?: string
  api_keys?: Record<string, string>
  skip_passkey_offer?: boolean
}

export interface User {
  id: number
  email: string
  name: string
  organization?: {
    id: number
    name: string
  } | null
  settings?: UserSettings
  is_staff?: boolean
  has_passkey?: boolean
  /** the Django admin's path, for staff only */
  admin_url?: string | null
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
