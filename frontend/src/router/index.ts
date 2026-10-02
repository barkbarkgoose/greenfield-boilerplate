import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  // Public, customer-facing pages: no account needed. `public` pages render
  // their own header instead of the signed-in navbar.
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/LandingView.vue'),
    meta: { public: true }
  },
  {
    path: '/book',
    name: 'book',
    component: () => import('@/views/IntakeView.vue'),
    meta: { public: true }
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresGuest: true, public: true }
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { requiresGuest: true, public: true }
  },

  // Customers: their garage (vehicles + repair history) and request threads.
  {
    path: '/account',
    name: 'account',
    component: () => import('@/views/AccountView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/account/requests/:id',
    name: 'account-request',
    component: () => import('@/views/CustomerRequestView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/claim/:token',
    name: 'claim',
    component: () => import('@/views/ClaimView.vue'),
    meta: { requiresAuth: true }
  },

  // The mechanic (staff users).
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/StaffDashboardView.vue'),
    meta: { requiresAuth: true, requiresStaff: true }
  },
  {
    path: '/dashboard/requests/:id',
    name: 'staff-request',
    component: () => import('@/views/StaffRequestView.vue'),
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

router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  // loadFromStorage also drops an expired token, so isAuthenticated below
  // correctly reports false once the JWT lifetime has elapsed.
  authStore.loadFromStorage()

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
