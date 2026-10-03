<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PublicHeader from '@/components/PublicHeader.vue'
import PublicFooter from '@/components/PublicFooter.vue'
import { business, partsPolicy } from '@/config/business'
import { fetchCatalog } from '@/services/intake'
import { formatMoney } from '@/utils/intake'
import type { Catalog } from '@/types/intake'

const catalog = ref<Catalog | null>(null)
const loadError = ref(false)

const leadDays = computed(() => catalog.value?.booking_lead_days ?? 14)
const pricedServices = computed(() => catalog.value?.services.filter((s) => !s.quote_required) ?? [])
const otherService = computed(() => catalog.value?.services.find((s) => s.quote_required))

const steps = [
  {
    title: 'Send your VIN and the work',
    body: 'Pick from the menu below and see your labor estimate right away. Your VIN lets me order exactly the right parts.'
  },
  {
    title: 'I order parts ahead, at cost',
    body: 'Jobs are booked about two weeks out so I can find the best price on your parts. You pay exactly what I pay, with zero markup.'
  },
  {
    title: 'I come to you',
    body: 'Home, work, or wherever the car is parked safely. You get the job done without a trip to the shop.'
  }
]

onMounted(async () => {
  try {
    catalog.value = await fetchCatalog()
  } catch {
    loadError.value = true
  }
})
</script>

<template>
  <div class="flex min-h-screen flex-col bg-slate-50">
    <PublicHeader />

    <!-- Hero -->
    <section class="relative overflow-hidden bg-slate-900 text-white">
      <div class="absolute inset-0 opacity-20" aria-hidden="true">
        <div class="absolute -right-32 -top-32 h-96 w-96 rounded-full bg-amber-400 blur-3xl" />
        <div class="absolute -bottom-40 -left-20 h-96 w-96 rounded-full bg-sky-500 blur-3xl" />
      </div>
      <div class="relative mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-[1.3fr_1fr] lg:items-center">
        <div>
          <p class="text-sm font-semibold uppercase tracking-widest text-amber-400">Mobile mechanic</p>
          <h1 class="mt-3 text-4xl font-extrabold tracking-tight sm:text-5xl">
            {{ business.tagline }}
          </h1>
          <p class="mt-5 max-w-xl text-lg text-slate-300">
            Brakes, suspension, tune-ups and more with upfront, flat labor prices. No shop
            markup, no waiting room. {{ business.serviceArea }}.
          </p>
          <div class="mt-8 flex flex-col gap-3 sm:flex-row">
            <router-link
              :to="{ name: 'book' }"
              class="rounded-xl bg-amber-400 px-6 py-3 text-center text-base font-semibold text-slate-900 shadow-lg shadow-amber-400/20 hover:bg-amber-300"
            >
              Get a price &amp; book
            </router-link>
            <router-link
              :to="{ name: 'book', query: { mode: 'callback' } }"
              class="rounded-xl border border-slate-600 px-6 py-3 text-center text-base font-semibold text-white hover:border-slate-400 hover:bg-slate-800"
            >
              Just have me contact you
            </router-link>
          </div>
        </div>
        <ul class="grid gap-3 text-sm">
          <li class="rounded-2xl border border-amber-400/40 bg-slate-800/60 p-4">
            <p class="font-semibold text-amber-400">{{ partsPolicy.headline }}</p>
            <p class="mt-1 text-slate-400">You pay exactly what I pay for parts, nothing more.</p>
          </li>
          <li class="rounded-2xl border border-slate-700 bg-slate-800/60 p-4">
            <p class="font-semibold text-white">Flat labor pricing</p>
            <p class="mt-1 text-slate-400">Every job is priced by the time it really takes.</p>
          </li>
          <li class="rounded-2xl border border-slate-700 bg-slate-800/60 p-4">
            <p class="font-semibold text-white">Bundle and save</p>
            <p class="mt-1 text-slate-400">Shared teardown time is discounted, oil changes are free on big jobs, and long jobs drop to a lower hourly rate.</p>
          </li>
          <li class="rounded-2xl border border-slate-700 bg-slate-800/60 p-4">
            <p class="font-semibold text-white">Booked ~{{ leadDays }} days out</p>
            <p class="mt-1 text-slate-400">Time to order the right parts at the right price.</p>
          </li>
        </ul>
      </div>
    </section>

    <!-- How it works -->
    <section class="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6">
      <h2 class="text-2xl font-bold text-slate-900 sm:text-3xl">How it works</h2>
      <ol class="mt-8 grid gap-6 md:grid-cols-3">
        <li v-for="(step, index) in steps" :key="step.title" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <span class="flex h-9 w-9 items-center justify-center rounded-full bg-slate-900 text-sm font-bold text-amber-400">
            {{ index + 1 }}
          </span>
          <h3 class="mt-4 font-semibold text-slate-900">{{ step.title }}</h3>
          <p class="mt-2 text-sm text-slate-600">{{ step.body }}</p>
        </li>
      </ol>
    </section>

    <!-- Pricing -->
    <section id="pricing" class="scroll-mt-20 border-y border-slate-200 bg-white">
      <div class="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div class="max-w-2xl">
          <h2 class="text-2xl font-bold text-slate-900 sm:text-3xl">Services &amp; labor prices</h2>
          <p class="mt-3 text-slate-600">
            Prices are labor only. Parts are quoted separately once I look up your VIN, and
            billed at cost with zero markup.
            <template v-if="catalog">
              Each visit includes a {{ formatMoney(catalog.service_call_fee) }} service call fee
              that covers travel.
            </template>
          </p>
        </div>

        <p v-if="loadError" class="mt-8 rounded-xl bg-red-50 p-4 text-sm text-red-700">
          Prices couldn't be loaded right now. You can still
          <router-link :to="{ name: 'book', query: { mode: 'callback' } }" class="font-semibold underline">ask me to contact you</router-link>.
        </p>
        <div v-else-if="!catalog" class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="n in 6" :key="n" class="h-28 animate-pulse rounded-2xl bg-slate-100" />
        </div>
        <template v-else>
          <div class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div
              v-for="service in pricedServices"
              :key="service.key"
              class="flex flex-col rounded-2xl border border-slate-200 p-5"
            >
              <div class="flex items-baseline justify-between gap-3">
                <h3 class="font-semibold text-slate-900">{{ service.name }}</h3>
                <p class="whitespace-nowrap text-lg font-bold text-slate-900">
                  {{ formatMoney(service.price) }}<span v-if="service.unit" class="text-sm font-medium text-slate-500">/{{ service.unit }}</span>
                </p>
              </div>
              <p class="mt-2 flex-1 text-sm text-slate-600">{{ service.description }}</p>
            </div>
            <div v-if="otherService" class="flex flex-col rounded-2xl border border-dashed border-slate-300 p-5">
              <div class="flex items-baseline justify-between gap-3">
                <h3 class="font-semibold text-slate-900">{{ otherService.name }}</h3>
                <p class="text-sm font-semibold text-slate-500">Quoted</p>
              </div>
              <p class="mt-2 text-sm text-slate-600">{{ otherService.description }}</p>
            </div>
          </div>

          <div class="mt-8 grid gap-4 md:grid-cols-2">
            <div
              v-for="bundle in catalog.bundles"
              :key="bundle.key"
              class="rounded-2xl bg-emerald-50 p-5 ring-1 ring-emerald-200"
            >
              <p class="font-semibold text-emerald-900">
                {{ bundle.name }}: save {{ formatMoney(bundle.discount_per_unit) }} per axle
              </p>
              <p class="mt-1 text-sm text-emerald-800">{{ bundle.description }}</p>
            </div>
            <div
              v-for="deal in catalog.deals"
              :key="deal.key"
              class="rounded-2xl bg-emerald-50 p-5 ring-1 ring-emerald-200"
            >
              <p class="font-semibold text-emerald-900">{{ deal.name }}</p>
              <p class="mt-1 text-sm text-emerald-800">{{ deal.description }}</p>
            </div>
          </div>
        </template>
      </div>
    </section>

    <!-- Policies -->
    <section class="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6">
      <h2 class="text-2xl font-bold text-slate-900 sm:text-3xl">Good to know</h2>
      <div class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div class="rounded-2xl bg-emerald-50 p-6 ring-1 ring-emerald-200">
          <h3 class="font-semibold text-emerald-900">{{ partsPolicy.headline }}, guaranteed</h3>
          <p class="mt-2 text-sm text-emerald-900/80">{{ partsPolicy.long }}</p>
        </div>
        <div class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <h3 class="font-semibold text-slate-900">Booking ~{{ leadDays }} days ahead</h3>
          <p class="mt-2 text-sm text-slate-600">
            Most appointments are booked about two weeks out so I can order parts for your
            exact vehicle.
          </p>
        </div>
        <div class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <h3 class="font-semibold text-slate-900">Same-week emergency jobs</h3>
          <p class="mt-2 text-sm text-slate-600">
            Need it sooner? Jobs within {{ catalog?.emergency_window_days ?? 7 }} days are
            possible when the schedule allows, with a
            {{ catalog ? formatMoney(catalog.emergency_fee) : '' }} emergency fee.
          </p>
        </div>
        <div class="rounded-2xl bg-amber-50 p-6 ring-1 ring-amber-200">
          <h3 class="font-semibold text-amber-900">Short-notice parts cost more</h3>
          <p class="mt-2 text-sm text-amber-900/80">
            When there isn't time to order ahead, parts usually have to come from a local
            store at retail prices, which are likely to be higher.
          </p>
        </div>
      </div>

      <div class="mt-12 flex flex-col items-start gap-4 rounded-3xl bg-slate-900 p-8 text-white sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p class="text-xl font-bold">Ready when you are.</p>
          <p class="mt-1 text-slate-300">Get your estimate in about two minutes.</p>
        </div>
        <router-link
          :to="{ name: 'book' }"
          class="rounded-xl bg-amber-400 px-6 py-3 font-semibold text-slate-900 hover:bg-amber-300"
        >
          Start booking
        </router-link>
      </div>
    </section>

    <PublicFooter class="mt-auto" />
  </div>
</template>
