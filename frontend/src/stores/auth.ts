import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { User, LoginCredentials, RegisterRequest, LoginResponse, RegisterResponse } from '@/types/auth'
import api from '@/services/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null)
  const user = ref<User | null>(null)

  const isAuthenticated = computed(() => !!token.value)

  function loadFromStorage(): void {
    const storedToken = localStorage.getItem('auth_token')
    const storedUser = localStorage.getItem('auth_user')
    if (storedToken) {
      token.value = storedToken
    }
    if (storedUser) {
      user.value = JSON.parse(storedUser)
    }
  }

  async function login(credentials: LoginCredentials): Promise<void> {
    const response = await api.post<LoginResponse>('/api/v1/auth/login/', credentials)
    token.value = response.data.access
    localStorage.setItem('auth_token', response.data.access)
    if (response.data.refresh) {
      localStorage.setItem('refresh_token', response.data.refresh)
    }
  }

  async function register(payload: RegisterRequest): Promise<void> {
    const response = await api.post<RegisterResponse>('/api/v1/auth/register/', payload)
    token.value = response.data.token
    localStorage.setItem('auth_token', response.data.token)
    user.value = {
      id: response.data.id,
      email: response.data.email,
      name: response.data.name,
      organization: response.data.organization
    }
    localStorage.setItem('auth_user', JSON.stringify(user.value))
  }

  function logout(): void {
    token.value = null
    user.value = null
    localStorage.removeItem('auth_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('auth_user')
  }

  return {
    token,
    user,
    isAuthenticated,
    loadFromStorage,
    login,
    register,
    logout
  }
})
