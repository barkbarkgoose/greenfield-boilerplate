import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { currentLocale, isLocale, setLocale } from '@/i18n'
import { applyPageMeta } from '@/i18n/seo'

const routes: RouteRecordRaw[] = [
  // Public, customer-facing pages: no account needed. `localized` pages also
  // have a Spanish address (/es, /es/order) for search engines; every other
  // page follows the visitor's saved language. See README "Translations".
  {
    path: '/:locale(es)?',
    name: 'home',
    component: () => import('@/views/LandingView.vue'),
    meta: { localized: true }
  },
  {
    path: '/:locale(es)?/order',
    name: 'order',
    component: () => import('@/views/OrderView.vue'),
    meta: { localized: true }
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
    // Accounts that require a passkey and haven't saved one yet land here.
    path: '/passkey-setup',
    name: 'passkey-setup',
    component: () => import('@/views/PasskeySetupView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: () => import('@/views/ForgotPasswordView.vue'),
    meta: { requiresGuest: true }
  },
  {
    // The link emailed by the password reset; works signed in or out.
    path: '/reset-password/:uid/:token',
    name: 'reset-password',
    component: () => import('@/views/ResetPasswordView.vue')
  },

  // Customers: their orders, order pages and claim links.
  {
    path: '/account',
    name: 'account',
    component: () => import('@/views/AccountView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/account/orders/:id',
    name: 'account-order',
    component: () => import('@/views/CustomerOrderView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/claim/:token',
    name: 'claim',
    component: () => import('@/views/ClaimView.vue'),
    meta: { requiresAuth: true }
  },

  // Staff: orders and the dispatch board.
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/StaffDashboardView.vue'),
    meta: { requiresAuth: true, requiresStaff: true }
  },
  {
    path: '/dashboard/orders/:id',
    name: 'staff-order',
    component: () => import('@/views/StaffOrderView.vue'),
    meta: { requiresAuth: true, requiresStaff: true }
  },
  {
    path: '/dashboard/dispatch',
    name: 'dispatch',
    component: () => import('@/views/StaffDispatchView.vue'),
    meta: { requiresAuth: true, requiresStaff: true }
  },

  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { requiresAuth: true }
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, behavior: 'smooth' }
    return { top: 0 }
  }
})

router.beforeEach(async (to, _from, next) => {
  // Language: ?lang=es (from email links) or an /es/ address sets it; a
  // Spanish-speaking visitor on an English address is sent to the /es/ one.
  if (isLocale(to.query.lang)) setLocale(to.query.lang)
  if (to.meta.localized) {
    if (to.params.locale === 'es') {
      setLocale('es')
    } else if (currentLocale() === 'es') {
      return next({ name: to.name!, params: { ...to.params, locale: 'es' }, query: to.query, hash: to.hash })
    }
  }

  const authStore = useAuthStore()
  // loadFromStorage renews a short-lived access token (or drops an ended
  // session), so isAuthenticated below is accurate.
  await authStore.loadFromStorage()

  // A session that must save a passkey can't do anything else yet (the API
  // enforces this too); send it to the setup page.
  const passkeyExempt = ['passkey-setup', 'login', 'forgot-password', 'reset-password']
  if (authStore.passkeySetupRequired && !passkeyExempt.includes(String(to.name))) {
    return next({ name: 'passkey-setup', query: { redirect: to.fullPath } })
  }

  // Role checks here are UX only; the API enforces permissions.
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else if (to.meta.requiresStaff && !authStore.isStaff) {
    next({ name: 'account' })
  } else if (to.meta.requiresGuest && authStore.isAuthenticated) {
    next(authStore.homeRoute)
  } else {
    next()
  }
})

export default router

router.afterEach((to) => applyPageMeta(to))
