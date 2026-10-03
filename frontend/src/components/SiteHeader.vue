<script setup lang="ts">
// The one header for every page, signed in or not. Signed-in people get an
// account menu on the right; guests who tap "My garage" get a dialog that
// points them to sign up or sign in instead of a bare login redirect.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { business } from '@/config/business'
import { useAuthStore } from '@/stores/auth'
import LanguageToggle from '@/components/LanguageToggle.vue'
import GarageSignInDialog from '@/components/GarageSignInDialog.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const isMenuOpen = ref(false)
const menu = ref<HTMLElement | null>(null)
const garageDialog = ref<InstanceType<typeof GarageSignInDialog> | null>(null)

const accountLink = computed(() =>
  authStore.isStaff
    ? { to: '/dashboard', label: t('site-header__nav-link--dashboard') }
    : { to: '/account', label: t('site-header__nav-link--garage') }
)
const accountLinkActive = computed(() => route.path.startsWith(authStore.isStaff ? '/dashboard' : '/account'))

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

function openGarage() {
  if (!authStore.isAuthenticated) garageDialog.value?.open()
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

const linkClass = 'rounded-lg px-3 py-2 text-sm font-medium text-slate-300 hover:text-white'
const menuItemClass =
  'flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 hover:text-slate-900'
</script>

<template>
  <header class="site-header sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur">
    <div class="mx-auto flex h-16 max-w-6xl items-center justify-between gap-2 px-4 sm:px-6">
      <router-link :to="{ name: 'home' }" class="flex shrink-0 items-center gap-2 text-white" :aria-label="t('site-header__home-link', { business: business.name })">
        <span class="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-400 text-slate-900">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M14.7 6.3a4 4 0 00-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 005.2-5.4l-2.6 2.6-2.4-.6-.6-2.4 2.6-2.6z" />
          </svg>
        </span>
        <span class="hidden text-lg font-bold tracking-tight lg:inline">{{ business.name }}</span>
      </router-link>

      <nav class="flex items-center gap-1 sm:gap-2">
        <router-link :to="{ name: 'home', hash: '#pricing' }" :class="[linkClass, 'hidden md:block']">
          {{ t('site-header__nav-link--pricing') }}
        </router-link>
        <router-link :to="{ name: 'book', query: { mode: 'callback' } }" :class="[linkClass, 'hidden md:block']">
          {{ t('site-header__nav-link--contact') }}
        </router-link>
        <!-- Guests get a button that opens the sign-in dialog instead of a link. -->
        <component
          :is="authStore.isAuthenticated ? RouterLink : 'button'"
          v-bind="authStore.isAuthenticated ? { to: accountLink.to } : { type: 'button', 'aria-haspopup': 'dialog' }"
          class="site-header__garage-link flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm font-medium sm:px-3"
          :class="accountLinkActive ? 'bg-slate-800 text-white' : 'text-slate-300 hover:text-white'"
          :aria-label="accountLink.label"
          @click="openGarage"
        >
          <svg class="h-5 w-5 sm:hidden" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 10.5L12 4l9 6.5V20a1 1 0 01-1 1H4a1 1 0 01-1-1v-9.5zM7 21v-7h10v7M7 17.5h10" />
          </svg>
          <span class="hidden whitespace-nowrap sm:inline">{{ accountLink.label }}</span>
        </component>
        <LanguageToggle v-if="!authStore.isStaff" dark />
        <router-link
          :to="{ name: 'book' }"
          class="whitespace-nowrap rounded-lg bg-amber-400 px-3 py-2 text-sm font-semibold text-slate-900 shadow-sm hover:bg-amber-300 sm:px-4"
        >
          <span class="hidden sm:inline">{{ t('site-header__cta') }}</span>
          <span class="sm:hidden">{{ t('site-header__cta--short') }}</span>
        </router-link>

        <div v-if="authStore.isAuthenticated" ref="menu" class="relative">
          <button
            type="button"
            :aria-label="t('app-nav__menu-button')"
            :aria-expanded="isMenuOpen"
            aria-haspopup="menu"
            class="flex items-center rounded-full p-0.5 focus:outline-none focus:ring-2 focus:ring-amber-400/60"
            @click.stop="isMenuOpen = !isMenuOpen"
            @keydown.esc="closeMenu"
          >
            <span class="flex h-9 w-9 items-center justify-center rounded-full bg-slate-700 text-sm font-bold text-white ring-1 ring-slate-600">
              {{ initials }}
            </span>
          </button>

          <div
            v-if="isMenuOpen"
            class="absolute right-0 top-full z-40 mt-2 w-64 rounded-2xl border border-slate-200 bg-white p-2 shadow-xl"
            role="menu"
            @keydown.esc="closeMenu"
          >
            <div class="border-b border-slate-100 px-3 py-3">
              <p class="truncate text-sm font-semibold text-slate-900">{{ displayName }}</p>
              <p class="mt-0.5 truncate text-xs text-slate-500">{{ authStore.user?.email }}</p>
            </div>
            <div class="mt-2">
              <router-link :to="accountLink.to" role="menuitem" :class="menuItemClass">{{ accountLink.label }}</router-link>
              <router-link :to="{ name: 'home', hash: '#pricing' }" role="menuitem" :class="[menuItemClass, 'md:hidden']">
                {{ t('site-header__nav-link--pricing') }}
              </router-link>
              <router-link :to="{ name: 'book', query: { mode: 'callback' } }" role="menuitem" :class="[menuItemClass, 'md:hidden']">
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
      <GarageSignInDialog ref="garageDialog" />
    </Teleport>
  </header>
</template>
