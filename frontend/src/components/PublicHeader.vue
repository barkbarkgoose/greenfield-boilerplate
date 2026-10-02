<script setup lang="ts">
import { business } from '@/config/business'
</script>

<template>
  <header class="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur">
    <div class="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
      <router-link to="/" class="flex items-center gap-2 text-white">
        <span class="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-400 text-slate-900">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M14.7 6.3a4 4 0 00-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 005.2-5.4l-2.6 2.6-2.4-.6-.6-2.4 2.6-2.6z" />
          </svg>
        </span>
        <span class="text-lg font-bold tracking-tight">{{ business.name }}</span>
      </router-link>
      <nav class="flex items-center gap-1 sm:gap-2">
        <router-link
          :to="{ path: '/', hash: '#pricing' }"
          class="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-300 hover:text-white sm:block"
        >
          Pricing
        </router-link>
        <router-link
          :to="{ name: 'book', query: { mode: 'callback' } }"
          class="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-300 hover:text-white sm:block"
        >
          Contact me
        </router-link>
        <router-link
          :to="{ name: 'book' }"
          class="rounded-lg bg-amber-400 px-4 py-2 text-sm font-semibold text-slate-900 shadow-sm hover:bg-amber-300"
        >
          Book service
        </router-link>
      </nav>
    </div>
  </header>
</template>
