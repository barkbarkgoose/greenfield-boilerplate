<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import PublicHeader from '@/components/PublicHeader.vue'
import PublicFooter from '@/components/PublicFooter.vue'
import { fetchCatalog } from '@/services/intake'
import { formatMoney } from '@/utils/intake'
import type { Catalog } from '@/types/intake'

// Text keys are named after the section they appear in: landing-hero__*,
// landing-steps__*, landing-pricing__*, landing-policies__*, landing-cta__*.
const { t, locale } = useI18n()

const catalog = ref<Catalog | null>(null)
const loadError = ref(false)

const leadDays = computed(() => catalog.value?.booking_lead_days ?? 14)
const pricedServices = computed(() => catalog.value?.services.filter((s) => !s.quote_required) ?? [])
const otherService = computed(() => catalog.value?.services.find((s) => s.quote_required))
const steps = [1, 2, 3]

async function load() {
  try {
    // Service names and deals come from the API in the current language.
    catalog.value = await fetchCatalog()
    loadError.value = false
  } catch {
    loadError.value = true
  }
}

onMounted(load)
watch(locale, load)
</script>

<template>
  <div class="flex min-h-screen flex-col bg-slate-50">
    <PublicHeader />

    <section class="landing-hero relative overflow-hidden bg-slate-900 text-white">
      <div class="absolute inset-0 opacity-20" aria-hidden="true">
        <div class="absolute -right-32 -top-32 h-96 w-96 rounded-full bg-amber-400 blur-3xl" />
        <div class="absolute -bottom-40 -left-20 h-96 w-96 rounded-full bg-sky-500 blur-3xl" />
      </div>
      <div class="relative mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-[1.3fr_1fr] lg:items-center">
        <div>
          <p class="text-sm font-semibold uppercase tracking-widest text-amber-400">{{ t('landing-hero__eyebrow') }}</p>
          <h1 class="mt-3 text-4xl font-extrabold tracking-tight sm:text-5xl">{{ t('landing-hero__title') }}</h1>
          <p class="mt-5 max-w-xl text-lg text-slate-300">
            {{ t('landing-hero__intro') }} {{ t('site-footer__service-area') }}.
          </p>
          <div class="mt-8 flex flex-col gap-3 sm:flex-row">
            <router-link
              :to="{ name: 'book' }"
              class="rounded-xl bg-amber-400 px-6 py-3 text-center text-base font-semibold text-slate-900 shadow-lg shadow-amber-400/20 hover:bg-amber-300"
            >
              {{ t('landing-hero__cta--primary') }}
            </router-link>
            <router-link
              :to="{ name: 'book', query: { mode: 'callback' } }"
              class="rounded-xl border border-slate-600 px-6 py-3 text-center text-base font-semibold text-white hover:border-slate-400 hover:bg-slate-800"
            >
              {{ t('landing-hero__cta--secondary') }}
            </router-link>
          </div>
        </div>
        <ul class="grid gap-3 text-sm">
          <li class="rounded-2xl border border-amber-400/40 bg-slate-800/60 p-4">
            <p class="font-semibold text-amber-400">{{ t('parts-policy__headline') }}</p>
            <p class="mt-1 text-slate-400">{{ t('landing-hero__highlight-body--parts') }}</p>
          </li>
          <li class="rounded-2xl border border-slate-700 bg-slate-800/60 p-4">
            <p class="font-semibold text-white">{{ t('landing-hero__highlight-title--flat') }}</p>
            <p class="mt-1 text-slate-400">{{ t('landing-hero__highlight-body--flat') }}</p>
          </li>
          <li class="rounded-2xl border border-slate-700 bg-slate-800/60 p-4">
            <p class="font-semibold text-white">{{ t('landing-hero__highlight-title--bundles') }}</p>
            <p class="mt-1 text-slate-400">{{ t('landing-hero__highlight-body--bundles') }}</p>
          </li>
          <li class="rounded-2xl border border-slate-700 bg-slate-800/60 p-4">
            <p class="font-semibold text-white">{{ t('landing-hero__highlight-title--lead-time', { days: leadDays }) }}</p>
            <p class="mt-1 text-slate-400">{{ t('landing-hero__highlight-body--lead-time') }}</p>
          </li>
        </ul>
      </div>
    </section>

    <section class="landing-steps mx-auto w-full max-w-6xl px-4 py-16 sm:px-6">
      <h2 class="text-2xl font-bold text-slate-900 sm:text-3xl">{{ t('landing-steps__title') }}</h2>
      <ol class="mt-8 grid gap-6 md:grid-cols-3">
        <li v-for="step in steps" :key="step" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <span class="flex h-9 w-9 items-center justify-center rounded-full bg-slate-900 text-sm font-bold text-amber-400">
            {{ step }}
          </span>
          <h3 class="mt-4 font-semibold text-slate-900">{{ t(`landing-steps__step-title--${step}`) }}</h3>
          <p class="mt-2 text-sm text-slate-600">{{ t(`landing-steps__step-body--${step}`) }}</p>
        </li>
      </ol>
    </section>

    <section id="pricing" class="landing-pricing scroll-mt-20 border-y border-slate-200 bg-white">
      <div class="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div class="max-w-2xl">
          <h2 class="text-2xl font-bold text-slate-900 sm:text-3xl">{{ t('landing-pricing__title') }}</h2>
          <p class="mt-3 text-slate-600">
            {{ t('landing-pricing__intro') }}
            <template v-if="catalog">{{ t('landing-pricing__service-call', { fee: formatMoney(catalog.service_call_fee) }) }}</template>
          </p>
        </div>

        <p v-if="loadError" class="mt-8 rounded-xl bg-red-50 p-4 text-sm text-red-700">
          {{ t('landing-pricing__load-error') }}
          <router-link :to="{ name: 'book', query: { mode: 'callback' } }" class="font-semibold underline">{{ t('landing-pricing__load-error-link') }}</router-link>.
        </p>
        <div v-else-if="!catalog" class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="n in 6" :key="n" class="h-28 animate-pulse rounded-2xl bg-slate-100" />
        </div>
        <template v-else>
          <div class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div v-for="service in pricedServices" :key="service.key" class="flex flex-col rounded-2xl border border-slate-200 p-5">
              <div class="flex items-baseline justify-between gap-3">
                <h3 class="font-semibold text-slate-900">{{ service.name }}</h3>
                <p class="whitespace-nowrap text-lg font-bold text-slate-900">
                  {{ formatMoney(service.price) }}<span v-if="service.unit" class="text-sm font-medium text-slate-500">/{{ t(`landing-pricing__unit--${service.unit}`) }}</span>
                </p>
              </div>
              <p class="mt-2 flex-1 text-sm text-slate-600">{{ service.description }}</p>
            </div>
            <div v-if="otherService" class="flex flex-col rounded-2xl border border-dashed border-slate-300 p-5">
              <div class="flex items-baseline justify-between gap-3">
                <h3 class="font-semibold text-slate-900">{{ otherService.name }}</h3>
                <p class="whitespace-nowrap text-sm font-semibold text-slate-500">{{ t('landing-pricing__quoted') }}</p>
              </div>
              <p class="mt-2 text-sm text-slate-600">{{ otherService.description }}</p>
            </div>
          </div>

          <div class="mt-8 grid gap-4 md:grid-cols-2">
            <div v-for="bundle in catalog.bundles" :key="bundle.key" class="rounded-2xl bg-emerald-50 p-5 ring-1 ring-emerald-200">
              <p class="font-semibold text-emerald-900">
                {{ t('landing-pricing__bundle-title', { name: bundle.name, amount: formatMoney(bundle.discount_per_unit) }) }}
              </p>
              <p class="mt-1 text-sm text-emerald-800">{{ bundle.description }}</p>
            </div>
            <div v-for="deal in catalog.deals" :key="deal.key" class="rounded-2xl bg-emerald-50 p-5 ring-1 ring-emerald-200">
              <p class="font-semibold text-emerald-900">{{ deal.name }}</p>
              <p class="mt-1 text-sm text-emerald-800">{{ deal.description }}</p>
            </div>
          </div>
        </template>
      </div>
    </section>

    <section class="landing-policies mx-auto w-full max-w-6xl px-4 py-16 sm:px-6">
      <h2 class="text-2xl font-bold text-slate-900 sm:text-3xl">{{ t('landing-policies__title') }}</h2>
      <div class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div class="rounded-2xl bg-emerald-50 p-6 ring-1 ring-emerald-200">
          <h3 class="font-semibold text-emerald-900">{{ t('landing-policies__card-title--parts') }}</h3>
          <p class="mt-2 text-sm text-emerald-900/80">{{ t('parts-policy__long') }}</p>
        </div>
        <div class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <h3 class="font-semibold text-slate-900">{{ t('landing-policies__card-title--lead-time', { days: leadDays }) }}</h3>
          <p class="mt-2 text-sm text-slate-600">{{ t('landing-policies__card-body--lead-time') }}</p>
        </div>
        <div class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <h3 class="font-semibold text-slate-900">{{ t('landing-policies__card-title--emergency') }}</h3>
          <p class="mt-2 text-sm text-slate-600">
            {{ t('landing-policies__card-body--emergency', {
              days: catalog?.emergency_window_days ?? 7,
              fee: catalog ? formatMoney(catalog.emergency_fee) : '—'
            }) }}
          </p>
        </div>
        <div class="rounded-2xl bg-amber-50 p-6 ring-1 ring-amber-200">
          <h3 class="font-semibold text-amber-900">{{ t('landing-policies__card-title--short-notice') }}</h3>
          <p class="mt-2 text-sm text-amber-900/80">{{ t('landing-policies__card-body--short-notice') }}</p>
        </div>
      </div>

      <div class="landing-cta mt-12 flex flex-col items-start gap-4 rounded-3xl bg-slate-900 p-8 text-white sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p class="text-xl font-bold">{{ t('landing-cta__title') }}</p>
          <p class="mt-1 text-slate-300">{{ t('landing-cta__body') }}</p>
        </div>
        <router-link :to="{ name: 'book' }" class="rounded-xl bg-amber-400 px-6 py-3 font-semibold text-slate-900 hover:bg-amber-300">
          {{ t('landing-cta__button') }}
        </router-link>
      </div>
    </section>

    <PublicFooter class="mt-auto" />
  </div>
</template>
