<script setup lang="ts">
import { business } from '@/config/business'

const year = new Date().getFullYear()
</script>

<template>
  <footer class="border-t border-slate-200 bg-white">
    <div class="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <div>
        <p class="font-semibold text-slate-700">{{ business.name }}</p>
        <p>{{ business.serviceArea }} · {{ business.hours }}</p>
      </div>
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
        <a :href="`tel:${business.phone.replace(/[^\d+]/g, '')}`" class="hover:text-slate-800">{{ business.phone }}</a>
        <a :href="`mailto:${business.email}`" class="hover:text-slate-800">{{ business.email }}</a>
        <span>© {{ year }}</span>
        <router-link to="/login" class="text-slate-400 hover:text-slate-600">Owner login</router-link>
      </div>
    </div>
  </footer>
</template>
