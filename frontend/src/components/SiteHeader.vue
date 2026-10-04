<script setup lang="ts">
// The one header for every page, signed in or not. Signed-in people get an
// account menu on the right; guests see a sign-in link there instead, and get
// a dialog pointing them to sign up or sign in if they tap "My orders".
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { business } from '@/config/business'
import { useAuthStore } from '@/stores/auth'
import LanguageToggle from '@/components/LanguageToggle.vue'
import AccountSignInDialog from '@/components/AccountSignInDialog.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const isMenuOpen = ref(false)
const menu = ref<HTMLElement | null>(null)
const ordersDialog = ref<InstanceType<typeof AccountSignInDialog> | null>(null)

// Dashboard only ever lives in the avatar dropdown, so the top-level bar
// looks the same for staff and customers; the orders shortcut button is
// customer-only.
const accountLink = computed(() =>
  authStore.isStaff
    ? { to: '/dashboard', label: t('site-header__nav-link--dashboard') }
    : { to: '/account', label: t('site-header__nav-link--orders') }
)
const ordersLinkActive = computed(() => route.path.startsWith('/account'))
const accountLinkActive = computed(() => route.path.startsWith(accountLink.value.to))

// Products/Contact are anchors/query modes on shared routes rather than their
// own paths, so matching the route name alone isn't enough to tell them apart.
const productsActive = computed(() => route.name === 'home' && route.hash === '#products')
const contactActive = computed(() => route.name === 'order' && route.query.mode === 'callback')
// Top-bar tabs signal "active" with an underline; the dropdown (a list menu,
// not a tab strip) uses a background highlight instead.
const activeLinkClass = 'text-white border-lime-400'
const inactiveLinkClass = 'text-stone-300 border-transparent hover:text-white'
const activeMenuItemClass = 'bg-stone-100 text-stone-900'

const displayName = computed(() => authStore.user?.name || authStore.user?.email || t('app-nav__account-fallback'))
const initials = computed(() => {
  const name = authStore.user?.name?.trim()
  if (name) {
    return name
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0])
      .join('')
      .toUpperCase()
  }
  return authStore.user?.email?.charAt(0).toUpperCase() || 'U'
})

function openOrders() {
  if (!authStore.isAuthenticated) ordersDialog.value?.open()
}

function closeMenu() {
  isMenuOpen.value = false
}

function handleLogout() {
  closeMenu()
  authStore.logout()
  router.push({ name: 'home' })
}

function handleDocumentClick(event: MouseEvent) {
  if (menu.value && !menu.value.contains(event.target as Node)) closeMenu()
}

watch(() => route.fullPath, closeMenu)
onMounted(() => document.addEventListener('click', handleDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', handleDocumentClick))

const linkClass = 'rounded-t-lg px-3 py-2 text-sm font-medium border-b-2 transition-colors'
const menuItemClass =
  'flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-stone-700 hover:bg-stone-50 hover:text-stone-900'
</script>

<template>
  <header class="site-header sticky top-0 z-30 border-b border-stone-800 bg-stone-900/95 backdrop-blur">
    <div class="mx-auto flex h-16 max-w-6xl items-center justify-between gap-2 px-4 sm:px-6">
      <router-link :to="{ name: 'home' }" class="flex shrink-0 items-center gap-2 text-white" :aria-label="t('site-header__home-link', { business: business.name })">
        <span class="flex h-9 w-9 items-center justify-center rounded-lg bg-lime-400 text-stone-900">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M2 16V8h11l3 4h4l2 3v1h-2M2 16h1m6 0h7M3 8l2-3h6l2 3" />
            <circle cx="6" cy="17" r="2" />
            <circle cx="18" cy="17" r="2" />
          </svg>
        </span>
        <span class="hidden text-lg font-bold tracking-tight lg:inline">{{ business.name }}</span>
      </router-link>

      <nav class="flex items-center gap-1 sm:gap-2">
        <router-link
          :to="{ name: 'home', hash: '#products' }"
          :class="[linkClass, 'hidden md:block', productsActive ? activeLinkClass : inactiveLinkClass]"
          :aria-current="productsActive ? 'page' : undefined"
        >
          {{ t('site-header__nav-link--products') }}
        </router-link>
        <router-link
          :to="{ name: 'order', query: { mode: 'callback' } }"
          :class="[linkClass, 'hidden md:block', contactActive ? activeLinkClass : inactiveLinkClass]"
          :aria-current="contactActive ? 'page' : undefined"
        >
          {{ t('site-header__nav-link--contact') }}
        </router-link>
        <!-- Orders shortcut is customer-only; staff reach the dashboard through the avatar menu instead, so the bar matches. -->
        <component
          v-if="!authStore.isStaff"
          :is="authStore.isAuthenticated ? RouterLink : 'button'"
          v-bind="authStore.isAuthenticated ? { to: '/account' } : { type: 'button', 'aria-haspopup': 'dialog' }"
          class="site-header__orders-link flex items-center gap-1.5 rounded-t-lg border-b-2 px-2.5 py-2 text-sm font-medium transition-colors sm:px-3"
          :class="ordersLinkActive ? activeLinkClass : inactiveLinkClass"
          :aria-label="t('site-header__nav-link--orders')"
          :aria-current="ordersLinkActive ? 'page' : undefined"
          @click="openOrders"
        >
          <svg class="h-5 w-5 sm:hidden" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          <span class="hidden whitespace-nowrap sm:inline">{{ t('site-header__nav-link--orders') }}</span>
        </component>
        <LanguageToggle dark />
        <router-link
          :to="{ name: 'order' }"
          class="whitespace-nowrap rounded-lg bg-lime-400 px-3 py-2 text-sm font-semibold text-stone-900 shadow-sm hover:bg-lime-300 sm:px-4"
        >
          <span class="hidden sm:inline">{{ t('site-header__cta') }}</span>
          <span class="sm:hidden">{{ t('site-header__cta--short') }}</span>
        </router-link>

        <!-- Guests get a sign-in link where the avatar sits once signed in. -->
        <router-link
          v-if="!authStore.isAuthenticated"
          :to="{ name: 'login' }"
          :class="[inactiveLinkClass, 'whitespace-nowrap rounded-t-lg border-b-2 px-2 py-2 text-sm font-medium transition-colors sm:px-3']"
        >
          {{ t('site-header__nav-link--sign-in') }}
        </router-link>

        <div v-if="authStore.isAuthenticated" ref="menu" class="relative">
          <button
            type="button"
            :aria-label="t('app-nav__menu-button')"
            :aria-expanded="isMenuOpen"
            aria-haspopup="menu"
            class="flex items-center rounded-full p-0.5 focus:outline-none focus:ring-2 focus:ring-lime-400/60"
            @click.stop="isMenuOpen = !isMenuOpen"
            @keydown.esc="closeMenu"
          >
            <span class="flex h-9 w-9 items-center justify-center rounded-full bg-stone-700 text-sm font-bold text-white ring-1 ring-stone-600">
              {{ initials }}
            </span>
          </button>

          <div
            v-if="isMenuOpen"
            class="absolute right-0 top-full z-40 mt-2 w-64 rounded-2xl border border-stone-200 bg-white p-2 shadow-xl"
            role="menu"
            @keydown.esc="closeMenu"
          >
            <div class="border-b border-stone-100 px-3 py-3">
              <div class="flex items-center gap-2">
                <p class="truncate text-sm font-semibold text-stone-900">{{ displayName }}</p>
                <span v-if="authStore.isStaff" class="shrink-0 rounded-full bg-lime-100 px-2 py-0.5 text-xs font-semibold text-lime-800">
                  {{ t('app-nav__badge--staff') }}
                </span>
              </div>
              <p class="mt-0.5 truncate text-xs text-stone-500">{{ authStore.user?.email }}</p>
            </div>
            <div class="mt-2">
              <router-link
                :to="accountLink.to"
                role="menuitem"
                :class="[menuItemClass, accountLinkActive && activeMenuItemClass]"
                :aria-current="accountLinkActive ? 'page' : undefined"
              >
                {{ accountLink.label }}
              </router-link>
              <router-link
                :to="{ name: 'home', hash: '#products' }"
                role="menuitem"
                :class="[menuItemClass, 'md:hidden', productsActive && activeMenuItemClass]"
                :aria-current="productsActive ? 'page' : undefined"
              >
                {{ t('site-header__nav-link--products') }}
              </router-link>
              <router-link
                :to="{ name: 'order', query: { mode: 'callback' } }"
                role="menuitem"
                :class="[menuItemClass, 'md:hidden', contactActive && activeMenuItemClass]"
                :aria-current="contactActive ? 'page' : undefined"
              >
                {{ t('site-header__nav-link--contact') }}
              </router-link>
              <router-link to="/settings" role="menuitem" :class="menuItemClass">{{ t('app-nav__menu-item--settings') }}</router-link>
              <button type="button" role="menuitem" :class="[menuItemClass, 'hover:bg-red-50 hover:text-red-700']" @click="handleLogout">
                {{ t('app-nav__menu-item--logout') }}
              </button>
            </div>
          </div>
        </div>
      </nav>
    </div>

    <!-- Outside the blurred header so the modal and its backdrop cover the page. -->
    <Teleport to="body">
      <AccountSignInDialog ref="ordersDialog" />
    </Teleport>
  </header>
</template>
