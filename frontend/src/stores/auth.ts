import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  User,
  LoginCredentials,
  RegisterRequest,
  LoginResponse,
  RegisterResponse
} from '@/types/auth'
import { isTokenExpired } from '@/utils/jwt'
import { validAccessToken } from '@/utils/session'
import {
  REFRESH_KEY,
  TOKEN_KEY,
  USER_KEY,
  clearStoredAuth
} from '@/utils/authStorage'
import api from '@/services/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null)
  const user = ref<User | null>(null)

  const isAuthenticated = computed(() => !!token.value && !isTokenExpired(token.value))
  const isStaff = computed(() => isAuthenticated.value && !!user.value?.is_staff)
  // Where a signed-in person lands: the mechanic's dashboard or the customer's garage.
  const homeRoute = computed(() => (isStaff.value ? '/dashboard' : '/account'))

  function clearAuthState(): void {
    token.value = null
    user.value = null
    clearStoredAuth()
  }

  /**
   * Load the session from storage, renewing the access token if it's about to
   * expire. A session that can't be renewed is treated as signed out, so the
   * router guard can send the person to /login.
   */
  async function loadFromStorage(): Promise<void> {
    const storedToken = await validAccessToken()
    if (!storedToken) {
      clearAuthState()
      return
    }

    const storedUser = localStorage.getItem(USER_KEY)

    token.value = storedToken
    if (storedUser) {
      user.value = JSON.parse(storedUser)
    }
  }

  function storeUser(nextUser: User): void {
    user.value = nextUser
    localStorage.setItem(USER_KEY, JSON.stringify(nextUser))
  }

  async function login(credentials: LoginCredentials): Promise<void> {
    const response = await api.post<LoginResponse>('/api/v1/auth/login/', credentials)
    token.value = response.data.access
    localStorage.setItem(TOKEN_KEY, response.data.access)
    if (response.data.refresh) {
      localStorage.setItem(REFRESH_KEY, response.data.refresh)
    }
    if (response.data.user) {
      storeUser(response.data.user)
    }
  }

  async function register(payload: RegisterRequest): Promise<void> {
    const response = await api.post<RegisterResponse>('/api/v1/auth/register/', payload)
    token.value = response.data.token
    localStorage.setItem(TOKEN_KEY, response.data.token)
    if (response.data.refresh) {
      localStorage.setItem(REFRESH_KEY, response.data.refresh)
    }
    storeUser({
      id: response.data.id,
      email: response.data.email,
      name: response.data.name,
      is_staff: !!response.data.is_staff
    })
  }

  function logout(): void {
    clearAuthState()
  }

  return {
    token,
    user,
    isAuthenticated,
    isStaff,
    homeRoute,
    loadFromStorage,
    login,
    register,
    logout
  }
})
