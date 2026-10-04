import axios from 'axios'
import type { AxiosError } from 'axios'
import router from '@/router'
import { clearStoredAuth } from '@/utils/authStorage'
import { validAccessToken } from '@/utils/session'
import { API_BASE_URL } from '@/services/apiBase'
import { currentLocale } from '@/i18n'

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json'
  }
})

api.interceptors.request.use(
  async (config) => {
    // Renews an about-to-expire access token first (see utils/session.ts).
    const token = await validAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // The API answers in this language (service names, errors, emails).
    config.headers['Accept-Language'] = currentLocale()
    return config
  },
  (error) => Promise.reject(error)
)

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status
    const requestUrl = error.config?.url ?? ''
    const isAuthAttempt =
      requestUrl.includes('/auth/login/') || requestUrl.includes('/auth/register/')

    // A 401 on a normal request means the session ended server-side (password
    // changed, account disabled). Clear the stored session and route to /login; the router guard re-reads
    // storage, so the in-memory auth state is reconciled on navigation.
    if (status === 401 && !isAuthAttempt) {
      clearStoredAuth()

      if (router.currentRoute.value.name !== 'login') {
        router.push({
          name: 'login',
          query: { redirect: router.currentRoute.value.fullPath }
        })
      }
    }

    return Promise.reject(error)
  }
)

export default api
