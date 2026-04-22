<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const isAuthenticated = computed(() => authStore.isAuthenticated)

const navItems = [
  { name: 'Dashboard', path: '/dashboard' },
]

function handleLogout() {
  authStore.logout()
  router.push('/login')
}
</script>

<template>
  <nav v-if="isAuthenticated" class="bg-white shadow-sm border-b border-gray-200">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex h-16 items-center justify-between">
        <!-- Logo -->
        <router-link to="/dashboard" class="flex-shrink-0">
          <span class="text-xl font-bold text-primary">App</span>
        </router-link>

        <!-- Nav Links -->
        <div class="hidden sm:flex sm:items-center sm:space-x-1">
          <router-link
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            class="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            :class="route.path === item.path 
              ? 'bg-primary text-white' 
              : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'"
          >
            {{ item.name }}
          </router-link>
        </div>

        <!-- Logout -->
        <button
          @click="handleLogout"
          class="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
        >
          Logout
        </button>
      </div>
    </div>
  </nav>
</template>
