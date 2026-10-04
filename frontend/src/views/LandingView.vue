<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { fetchCatalog, fetchEstimate } from '@/services/intake'
import { formatMoney } from '@/utils/format'
import type { Catalog, Plan } from '@/types/intake'

// Text keys are named after the section they appear in: landing-hero__*,
// landing-zip__*, landing-steps__*, landing-products__*, landing-delivery__*,
// landing-policies__*, landing-cta__*.
const { t, locale } = useI18n()

const catalog = ref<Catalog | null>(null)
const loadError = ref(false)
const steps = [1, 2, 3]

async function load() {
  try {
    // Product names come from the API in the current language.
    catalog.value = await fetchCatalog()
    loadError.value = false
  } catch {
    loadError.value = true
  }
}

onMounted(load)
watch(locale, load)

// --- "Do you deliver to me?" -------------------------------------------------------

const zip = ref('')
const zipResult = ref<Plan | null>(null)
const zipChecking = ref(false)
const zipError = ref(false)
const zipValid = computed(() => /^\d{5}$/.test(zip.value.trim()))

async function checkZip() {
  if (!zipValid.value) return
  zipChecking.value = true
  zipError.value = false
  try {
    zipResult.value = (await fetchEstimate([], zip.value.trim(), null)).plan
  } catch {
    zipError.value = true
  } finally {
    zipChecking.value = false
  }
}
</script>

<template>
  <div class="flex flex-1 flex-col">
    <section class="landing-hero relative overflow-hidden bg-stone-900 text-white">
      <div class="absolute inset-0 opacity-25" aria-hidden="true">
        <div class="absolute -right-32 -top-32 h-96 w-96 rounded-full bg-lime-500 blur-3xl" />
        <div class="absolute -bottom-40 -left-20 h-96 w-96 rounded-full bg-amber-700 blur-3xl" />
      </div>
      <div class="relative mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-[1.3fr_1fr] lg:items-center">
        <div>
          <p class="text-sm font-semibold uppercase tracking-widest text-lime-400">{{ t('landing-hero__eyebrow') }}</p>
          <h1 class="mt-3 text-4xl font-extrabold tracking-tight sm:text-5xl">{{ t('landing-hero__title') }}</h1>
          <p class="mt-5 max-w-xl text-lg text-stone-300">{{ t('landing-hero__intro') }} {{ t('site-footer__service-area') }}.</p>
          <div class="mt-8 flex flex-col gap-3 sm:flex-row">
            <router-link
              :to="{ name: 'order' }"
              class="rounded-xl bg-lime-500 px-6 py-3 text-center text-base font-semibold text-stone-900 shadow-lg shadow-lime-500/20 hover:bg-lime-400"
            >
              {{ t('landing-hero__cta--primary') }}
            </router-link>
            <router-link
              :to="{ name: 'order', query: { mode: 'callback' } }"
              class="rounded-xl border border-stone-600 px-6 py-3 text-center text-base font-semibold text-white hover:border-stone-400 hover:bg-stone-800"
            >
              {{ t('landing-hero__cta--secondary') }}
            </router-link>
          </div>
        </div>

        <!-- ZIP check -->
        <div class="landing-zip rounded-3xl border border-stone-700 bg-stone-800/70 p-6">
          <p class="font-semibold text-white">{{ t('landing-zip__title') }}</p>
          <p class="mt-1 text-sm text-stone-400">{{ t('landing-zip__intro') }}</p>
          <form class="mt-4 flex gap-2" @submit.prevent="checkZip">
            <input
              v-model="zip"
              type="text"
              inputmode="numeric"
              maxlength="5"
              autocomplete="postal-code"
              :placeholder="t('landing-zip__placeholder')"
              :aria-label="t('landing-zip__placeholder')"
              class="w-32 rounded-lg border border-stone-600 bg-stone-900 px-3 py-2.5 text-center text-lg tracking-widest text-white placeholder:text-stone-500 focus:outline-none focus:ring-2 focus:ring-lime-500"
            />
            <button type="submit" :disabled="!zipValid || zipChecking" class="flex-1 rounded-lg bg-white px-4 py-2.5 font-semibold text-stone-900 hover:bg-stone-100 disabled:opacity-50">
              {{ zipChecking ? t('landing-zip__checking') : t('landing-zip__button') }}
            </button>
          </form>
          <p v-if="zipError" class="mt-3 text-sm text-red-300">{{ t('landing-zip__error') }}</p>
          <div v-else-if="zipResult" class="mt-4 rounded-xl p-4 text-sm" :class="zipResult.coverage === 'serve' ? 'bg-lime-500/15 text-lime-100' : 'bg-amber-500/15 text-amber-100'">
            <p class="font-semibold">
              <template v-if="zipResult.coverage === 'serve'">
                {{ zipResult.city ? t('landing-zip__result-title--serve', { city: zipResult.city }) : t('landing-zip__result-title--serve-no-city') }}
              </template>
              <template v-else>{{ t(`landing-zip__result-title--${zipResult.coverage}`) }}</template>
            </p>
            <p class="mt-1 opacity-90">{{ t(`landing-zip__result-body--${zipResult.coverage}`) }}</p>
            <router-link
              :to="zipResult.coverage === 'serve' ? { name: 'order' } : { name: 'order', query: { mode: 'callback' } }"
              class="mt-3 inline-block font-semibold underline"
            >
              {{ zipResult.coverage === 'serve' ? t('landing-zip__result-link--serve') : t('landing-zip__result-link--other') }} →
            </router-link>
          </div>
        </div>
      </div>
    </section>

    <section class="landing-steps mx-auto w-full max-w-6xl px-4 py-16 sm:px-6">
      <h2 class="text-2xl font-bold text-stone-900 sm:text-3xl">{{ t('landing-steps__title') }}</h2>
      <ol class="mt-8 grid gap-6 md:grid-cols-3">
        <li v-for="step in steps" :key="step" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200">
          <span class="flex h-9 w-9 items-center justify-center rounded-full bg-stone-900 text-sm font-bold text-lime-400">{{ step }}</span>
          <h3 class="mt-4 font-semibold text-stone-900">{{ t(`landing-steps__step-title--${step}`) }}</h3>
          <p class="mt-2 text-sm text-stone-600">{{ t(`landing-steps__step-body--${step}`) }}</p>
        </li>
      </ol>
    </section>

    <section id="products" class="landing-products scroll-mt-20 border-y border-stone-200 bg-white">
      <div class="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div class="max-w-2xl">
          <h2 class="text-2xl font-bold text-stone-900 sm:text-3xl">{{ t('landing-products__title') }}</h2>
          <p class="mt-3 text-stone-600">{{ t('landing-products__intro') }}</p>
        </div>

        <p v-if="loadError" class="mt-8 rounded-xl bg-red-50 p-4 text-sm text-red-700">
          {{ t('landing-products__load-error') }}
          <router-link :to="{ name: 'order', query: { mode: 'callback' } }" class="font-semibold underline">{{ t('landing-products__load-error-link') }}</router-link>.
        </p>
        <div v-else-if="!catalog" class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="n in 6" :key="n" class="h-28 animate-pulse rounded-2xl bg-stone-100" />
        </div>
        <template v-else>
          <div class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div v-for="p in catalog.products" :key="p.key" class="flex flex-col rounded-2xl border border-stone-200 p-5">
              <div class="flex items-baseline justify-between gap-3">
                <h3 class="font-semibold text-stone-900">{{ p.name }}</h3>
                <p class="whitespace-nowrap text-lg font-bold text-stone-900">
                  {{ formatMoney(p.price_per_yard) }}<span class="text-sm font-medium text-stone-500">/{{ t('order-products__unit') }}</span>
                </p>
              </div>
              <p class="mt-2 flex-1 text-sm text-stone-600">{{ p.description }}</p>
              <div class="mt-3 flex items-center justify-between text-sm">
                <span class="text-stone-500">{{ p.min_yards > 1 ? t('order-products__minimum', { min: p.min_yards }) : '' }}</span>
                <router-link :to="{ name: 'order', query: { product: p.key } }" class="font-semibold text-lime-700 hover:text-lime-600">
                  {{ t('landing-products__order-link') }} →
                </router-link>
              </div>
            </div>
          </div>

          <div class="landing-delivery mt-8 grid gap-4 md:grid-cols-3">
            <div class="rounded-2xl bg-lime-50 p-5 ring-1 ring-lime-200">
              <p class="font-semibold text-lime-900">{{ t('landing-delivery__title--base', { fee: formatMoney(catalog.delivery_base_fee) }) }}</p>
              <p class="mt-1 text-sm text-lime-900/80">
                {{ t('landing-delivery__body--base', { miles: catalog.included_miles, perMile: formatMoney(catalog.per_mile_fee) }) }}
              </p>
            </div>
            <div class="rounded-2xl bg-lime-50 p-5 ring-1 ring-lime-200">
              <p class="font-semibold text-lime-900">{{ t('landing-delivery__title--loads') }}</p>
              <p class="mt-1 text-sm text-lime-900/80">{{ t('landing-delivery__body--loads') }}</p>
            </div>
            <div class="rounded-2xl bg-orange-50 p-5 ring-1 ring-orange-200">
              <p class="font-semibold text-orange-900">{{ t('landing-delivery__title--rush', { fee: formatMoney(catalog.rush_fee) }) }}</p>
              <p class="mt-1 text-sm text-orange-900/80">{{ t('landing-delivery__body--rush') }}</p>
            </div>
          </div>
        </template>
      </div>
    </section>

    <section class="landing-policies mx-auto w-full max-w-6xl px-4 py-16 sm:px-6">
      <h2 class="text-2xl font-bold text-stone-900 sm:text-3xl">{{ t('landing-policies__title') }}</h2>
      <div class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div v-for="card in ['access', 'amount', 'days', 'special']" :key="card" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200">
          <h3 class="font-semibold text-stone-900">{{ t(`landing-policies__card-title--${card}`) }}</h3>
          <p class="mt-2 text-sm text-stone-600">{{ t(`landing-policies__card-body--${card}`) }}</p>
        </div>
      </div>

      <div class="landing-cta mt-12 flex flex-col items-start gap-4 rounded-3xl bg-stone-900 p-8 text-white sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p class="text-xl font-bold">{{ t('landing-cta__title') }}</p>
          <p class="mt-1 text-stone-300">{{ t('landing-cta__body') }}</p>
        </div>
        <router-link :to="{ name: 'order' }" class="rounded-xl bg-lime-500 px-6 py-3 font-semibold text-stone-900 hover:bg-lime-400">
          {{ t('landing-cta__button') }}
        </router-link>
      </div>
    </section>
  </div>
</template>
