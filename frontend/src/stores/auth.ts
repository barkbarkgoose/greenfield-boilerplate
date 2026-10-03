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

  function loadFromStorage(): void {
    const storedToken = localStorage.getItem(TOKEN_KEY)

    // Treat a missing or expired/malformed access token as logged out so the
    // router guard can redirect to /login instead of leaving the UI broken.
    if (!storedToken || isTokenExpired(storedToken)) {
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
