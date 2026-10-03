<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { business, phoneHref } from '@/config/business'

const { t } = useI18n()
const year = new Date().getFullYear()
</script>

<template>
  <footer class="site-footer border-t border-slate-200 bg-white">
    <div class="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <div>
        <p class="font-semibold text-slate-700">{{ business.name }}</p>
        <p>{{ t('site-footer__service-area') }} · {{ t('site-footer__hours') }}</p>
      </div>
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
        <a :href="phoneHref()" class="hover:text-slate-800">{{ business.phone }}</a>
        <a :href="`mailto:${business.email}`" class="hover:text-slate-800">{{ business.email }}</a>
        <span>© {{ year }}</span>
      </div>
    </div>
  </footer>
</template>
