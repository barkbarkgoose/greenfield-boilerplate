import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  AuthConfig,
  User,
  LoginCredentials,
  LoginResponse,
  PasskeySetup,
  RegisterRequest,
  RegisterResponse,
  UserSettings,
  UserSettingsUpdate
} from '@/types/auth'
import { isTokenExpired } from '@/utils/jwt'
import {
  REFRESH_KEY,
  SETTINGS_KEY,
  TOKEN_KEY,
  USER_KEY,
  clearStoredAuth
} from '@/utils/authStorage'
import api from '@/services/api'
import { createPasskey, passkeysSupported, signInWithPasskey } from '@/services/passkeys'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null)
  const user = ref<User | null>(null)
  const userSettings = ref<UserSettings | null>(null)

  const isAuthenticated = computed(() => !!token.value && !isTokenExpired(token.value))

  // Set after a password sign-in when the server suggests adding a passkey; cleared by
  // "Not now". Not persisted, so the offer comes back on the next password sign-in.
  const passkeyOffer = ref(false)

  /** The add-a-passkey dialog to show: staff without a passkey can't dismiss it. */
  const passkeyPrompt = computed<PasskeySetup>(() => {
    if (!isAuthenticated.value || !user.value) return null
    if (user.value.is_staff && !user.value.has_passkey) return 'required'
    return passkeyOffer.value && passkeysSupported() ? 'offer' : null
  })

  function clearAuthState(): void {
    token.value = null
    user.value = null
    userSettings.value = null
    clearStoredAuth()
  }

  function loadFromStorage(): void {
    const storedToken = localStorage.getItem(TOKEN_KEY)

    // Treat a missing or expired/malformed access token as logged out so the
    // router guard can redirect to /login instead of leaving the UI broken.
    // Keep a still-valid refresh token, though: the guard uses it to get a new
    // access token silently instead of sending the user back to /login.
    if (!storedToken || isTokenExpired(storedToken)) {
      const refresh = localStorage.getItem(REFRESH_KEY)
      if (refresh && !isTokenExpired(refresh)) {
        token.value = null
        return
      }
      clearAuthState()
      return
    }

    const storedUser = localStorage.getItem(USER_KEY)
    const storedSettings = localStorage.getItem(SETTINGS_KEY)

    token.value = storedToken
    if (storedUser) {
      user.value = JSON.parse(storedUser)
    }
    if (storedSettings) {
      userSettings.value = JSON.parse(storedSettings)
    }
  }

  function storeUser(nextUser: User): void {
    user.value = nextUser
    localStorage.setItem(USER_KEY, JSON.stringify(nextUser))
    if (nextUser.settings) {
      userSettings.value = nextUser.settings
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(nextUser.settings))
    }
  }

  async function fetchUserSettings(): Promise<UserSettings | null> {
    if (!token.value) return null
    try {
      const response = await api.get<UserSettings>('/api/v1/auth/settings/')
      userSettings.value = response.data
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(response.data))
      if (user.value) {
        user.value.settings = response.data
        localStorage.setItem(USER_KEY, JSON.stringify(user.value))
      }
      return response.data
    } catch {
      return null
    }
  }

  async function updateUserSettings(settings: UserSettingsUpdate): Promise<UserSettings> {
    const response = await api.patch<UserSettings>('/api/v1/auth/settings/', settings)
    userSettings.value = response.data
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(response.data))
    if (user.value) {
      user.value.settings = response.data
      localStorage.setItem(USER_KEY, JSON.stringify(user.value))
    }
    return response.data
  }

  async function saveApiKey(provider: string, apiKey: string): Promise<boolean> {
    if (!token.value || !provider) return false
    try {
      await updateUserSettings({ api_keys: { [provider]: apiKey.trim() } })
      return true
    } catch {
      return false
    }
  }

  function startSession(data: LoginResponse): void {
    token.value = data.access
    localStorage.setItem(TOKEN_KEY, data.access)
    if (data.refresh) {
      localStorage.setItem(REFRESH_KEY, data.refresh)
    }
    if (data.user) {
      storeUser(data.user)
    }
    passkeyOffer.value = data.passkey_setup === 'offer'
  }

  async function login(credentials: LoginCredentials): Promise<void> {
    const response = await api.post<LoginResponse>('/api/v1/auth/login/', credentials)
    startSession(response.data)
  }

  async function loginWithPasskey(): Promise<void> {
    startSession(await signInWithPasskey())
  }

  function setHasPasskey(value: boolean): void {
    if (user.value && user.value.has_passkey !== value) storeUser({ ...user.value, has_passkey: value })
  }

  async function addPasskey(name = ''): Promise<void> {
    await createPasskey(name)
    passkeyOffer.value = false
    setHasPasskey(true)
  }

  /** "Not now" closes the offer; "Don't ask again" also saves that to the user's settings. */
  async function dismissPasskeyOffer(forever: boolean): Promise<void> {
    passkeyOffer.value = false
    if (forever) await updateUserSettings({ skip_passkey_offer: true })
  }

  // null until fetched. Both fail closed: registration hidden, and every page needs a
  // login unless the server says REQUIRE_LOGIN is off.
  const allowRegistration = ref<boolean | null>(null)
  const requireLogin = ref<boolean | null>(null)
  let configRequest: Promise<void> | null = null

  function loadAuthConfig(): Promise<void> {
    if (!configRequest) {
      configRequest = api
        .get<AuthConfig>('/api/v1/auth/config/')
        .then((response) => {
          allowRegistration.value = response.data.allow_registration
          requireLogin.value = response.data.require_login
        })
        .catch(() => {
          allowRegistration.value = false
          requireLogin.value = true
          configRequest = null // ask again on the next navigation
        })
    }
    return configRequest
  }

  async function register(payload: RegisterRequest): Promise<void> {
    const response = await api.post<RegisterResponse>('/api/v1/auth/register/', payload)
    token.value = response.data.token
    localStorage.setItem(TOKEN_KEY, response.data.token)
    storeUser({
      id: response.data.id,
      email: response.data.email,
      name: response.data.name,
      organization: response.data.organization
    })
    passkeyOffer.value = true
  }

  /** Forget the session here and revoke its refresh token (and any admin session) on the server. */
  async function logout(): Promise<void> {
    const refresh = localStorage.getItem(REFRESH_KEY)
    clearAuthState()
    passkeyOffer.value = false
    try {
      await api.post('/api/v1/auth/logout/', { refresh })
    } catch {
      // the local session is gone either way
    }
  }

  return {
    token,
    user,
    userSettings,
    isAuthenticated,
    loadFromStorage,
    fetchUserSettings,
    updateUserSettings,
    saveApiKey,
    login,
    loginWithPasskey,
    addPasskey,
    setHasPasskey,
    passkeyPrompt,
    dismissPasskeyOffer,
    allowRegistration,
    requireLogin,
    loadAuthConfig,
    register,
    logout
  }
})
