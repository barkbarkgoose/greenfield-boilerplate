import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { refreshAccessToken } from '@/services/api'
import { safeRedirect } from '@/utils/redirect'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { public: true }
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresGuest: true }
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { requiresGuest: true }
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue')
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue')
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

/** A sign-in redirect to a page the server renders (the Django admin), not one of ours. */
export function isServerPage(redirect: unknown): boolean {
  const path = safeRedirect(redirect)
  return path !== null && router.resolve(path).matched.length === 0
}

// Default-deny: every route needs a session, except the sign-in pages (`requiresGuest`)
// and, only while the server's REQUIRE_LOGIN is off, routes marked `meta: { public: true }`.
// A new page is protected until you opt it out. An expired access token is renewed from
// the refresh token before giving up and showing /login.
router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  authStore.loadFromStorage()

  if (!authStore.isAuthenticated && !to.meta.requiresGuest) {
    if (await refreshAccessToken()) authStore.loadFromStorage()
  }

  if (!authStore.isAuthenticated && !to.meta.requiresGuest) {
    if (to.meta.public) await authStore.loadAuthConfig()
    if (!(to.meta.public && authStore.requireLogin === false)) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }
  // Signed-in staff still come to /login on the way to the Django admin: the admin
  // session is opened by a passkey sign-in.
  if (to.meta.requiresGuest && authStore.isAuthenticated && !isServerPage(to.query.redirect)) {
    return { name: 'dashboard' }
  }
  return true
})

export default router
