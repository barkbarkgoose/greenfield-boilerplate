<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import axios from 'axios'
import TurnstileWidget from '@/components/TurnstileWidget.vue'
import QuoteBreakdown from '@/components/QuoteBreakdown.vue'
import { useAuthStore } from '@/stores/auth'
import { fetchMyOrder } from '@/services/account'
import { business, phoneHref } from '@/config/business'
import { fetchCatalog, fetchEstimate, submitOrder } from '@/services/intake'
import { cubicYards, formatDate, formatMoney, isDeliveryDay, isoDateFromToday, nextDeliveryDate } from '@/utils/format'
import { DRAFT_FIELDS, clearDraft, isEmptyDraft, loadDraft, saveDraft } from '@/utils/orderDraft'
import { DELIVERY_WINDOWS } from '@/types/intake'
import type { Catalog, DeliveryWindow, Estimate, ItemSelection, OrderCreated, RequestType } from '@/types/intake'

// Text keys follow the form's sections: order-header__*, order-location__*,
// order-products__*, order-calculator__*, order-date__*, order-placement__*,
// order-contact__*, order-quote__*, order-confirmation__*, order-errors__*.
const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const mode = computed<RequestType>(() => (route.query.mode === 'callback' ? 'callback' : 'delivery'))

function setMode(next: RequestType) {
  const query = { ...route.query }
  if (next === 'callback') query.mode = 'callback'
  else delete query.mode
  router.replace({ query })
  errors.value = {}
}

const catalog = ref<Catalog | null>(null)
const catalogError = ref(false)
const weekdays = computed(() => catalog.value?.delivery_weekdays ?? [0, 1, 2, 3, 4, 5])
const defaultDate = () => nextDeliveryDate(2, weekdays.value)

const form = reactive({
  name: '',
  phone: '',
  email: '',
  delivery_address: '',
  zip_code: '',
  preferred_date: nextDeliveryDate(2, [0, 1, 2, 3, 4, 5]),
  delivery_window: 'any' as DeliveryWindow,
  placement_notes: '',
  notes: '',
  // Honeypot: hidden from people, bots tend to fill it in.
  website: ''
})

// Consent checkboxes. Not saved with the draft: agreeing should be a fresh
// choice each time an order is sent.
const consent = reactive({ contact: false, marketing: false })
watch(
  () => consent.contact,
  (agreed) => {
    if (agreed) delete errors.value.contact_consent
  }
)

const captchaToken = ref('')
const captcha = ref<InstanceType<typeof TurnstileWidget> | null>(null)
const captchaRequired = computed(() => !!import.meta.env.VITE_TURNSTILE_SITE_KEY && !authStore.isAuthenticated)

// Selected products: key -> cubic yards.
const selected = reactive<Record<string, number>>({})
const selections = computed<ItemSelection[]>(() =>
  Object.entries(selected).map(([key, quantity]) => ({ key, quantity }))
)

function product(key: string) {
  return catalog.value?.products.find((p) => p.key === key)
}

function toggleProduct(key: string) {
  if (selected[key]) delete selected[key]
  else selected[key] = Math.max(product(key)?.min_yards ?? 1, 1)
}

function setYards(key: string, value: number) {
  const p = product(key)
  if (!p || !Number.isFinite(value)) return
  selected[key] = Math.min(Math.max(Math.round(value), p.min_yards), p.max_yards)
}

const zip = computed(() => form.zip_code.replace(/\D/g, '').slice(0, 5))
const zipComplete = computed(() => zip.value.length === 5)
const minDate = isoDateFromToday(0)
const maxDate = computed(() => isoDateFromToday(catalog.value?.max_days_ahead ?? 90))
const dateIsDeliveryDay = computed(() => !form.preferred_date || isDeliveryDay(form.preferred_date, weekdays.value))

// --- Coverage calculator ---------------------------------------------------------

const calculator = reactive({ open: false, length: '', width: '', depth: '4', product: '' })
const calculatedYards = computed(() =>
  cubicYards(Number(calculator.length), Number(calculator.width), Number(calculator.depth))
)

function useCalculated() {
  const key = calculator.product || Object.keys(selected)[0] || catalog.value?.products[0]?.key
  if (!key || !calculatedYards.value) return
  if (!selected[key]) toggleProduct(key)
  setYards(key, calculatedYards.value)
}

// --- Draft ------------------------------------------------------------------
// The form is saved in this browser as it's filled in (see utils/orderDraft),
// so a refresh or a detour to another page doesn't lose it.

const draftRestored = ref(false)
let draftTimer: ReturnType<typeof setTimeout> | undefined

function currentDraft() {
  return {
    form: Object.fromEntries(DRAFT_FIELDS.map((field) => [field, form[field]])),
    selected: { ...selected }
  }
}

function draftDefaults() {
  return { preferred_date: defaultDate(), delivery_window: 'any' }
}

function persistDraft() {
  clearTimeout(draftTimer)
  // Once sent, the form isn't a draft any more.
  if (submitted.value) return
  const draft = currentDraft()
  if (isEmptyDraft(draft, draftDefaults())) clearDraft()
  else saveDraft(draft)
}

function restoreDraft() {
  const draft = loadDraft()
  if (!draft) return
  for (const field of DRAFT_FIELDS) {
    const value = draft.form[field]
    if (value === undefined) continue
    // A saved date that has since passed falls back to the default.
    if (field === 'preferred_date' && value < minDate) continue
    ;(form as Record<string, string>)[field] = value
  }
  Object.assign(selected, draft.selected)
  draftRestored.value = !isEmptyDraft(currentDraft(), draftDefaults())
}

function clearForm() {
  startOver()
  Object.assign(form, { name: '', phone: '', email: '', delivery_address: '', zip_code: '', placement_notes: '' })
  clearDraft()
  draftRestored.value = false
}

watch([form, selected], () => {
  clearTimeout(draftTimer)
  draftTimer = setTimeout(persistDraft, 300)
}, { deep: true })

// Save right away when leaving: route change, refresh or closing the tab.
onBeforeUnmount(persistDraft)
onMounted(() => window.addEventListener('pagehide', persistDraft))
onBeforeUnmount(() => window.removeEventListener('pagehide', persistDraft))

// --- Live coverage, routing and quote ------------------------------------------

const estimate = ref<Estimate | null>(null)
const estimating = ref(false)
let estimateTimer: ReturnType<typeof setTimeout> | undefined
let estimateRequest = 0

watch(
  // Re-fetch on language change too: product names come from the API.
  [selections, zip, () => form.preferred_date, mode, locale],
  () => {
    clearTimeout(estimateTimer)
    if (!zipComplete.value) {
      estimate.value = null
      estimating.value = false
      return
    }
    estimating.value = true
    estimateTimer = setTimeout(async () => {
      const requestId = ++estimateRequest
      try {
        // Only ask about the date when it's one we deliver on; the field shows its own error.
        const date = form.preferred_date && dateIsDeliveryDay.value ? form.preferred_date : null
        const result = await fetchEstimate(mode.value === 'delivery' ? selections.value : [], zip.value, date)
        if (requestId === estimateRequest) estimate.value = result
      } catch {
        if (requestId === estimateRequest) estimate.value = null
      } finally {
        if (requestId === estimateRequest) estimating.value = false
      }
    }, 300)
  },
  { deep: true }
)
onBeforeUnmount(() => clearTimeout(estimateTimer))

const plan = computed(() => estimate.value?.plan ?? null)
const quote = computed(() => (mode.value === 'delivery' ? estimate.value?.quote ?? null : null))
// Online ordering only works where we "serve"; elsewhere it's a special request.
const coverage = computed(() => plan.value?.coverage ?? null)
const needsSpecialRequest = computed(() => mode.value === 'delivery' && (coverage.value === 'contact' || coverage.value === 'outside'))
const shipsFrom = computed(() => [...new Set((plan.value?.loads ?? []).map((l) => l.yard_name).filter(Boolean))])
const stockProblems = computed(() => (plan.value?.problems ?? []).filter((p) => p.code === 'out_of_stock'))
const isRush = computed(() => !!quote.value?.scheduling.is_rush)

function useNextDate() {
  if (plan.value?.next_available_date) form.preferred_date = plan.value.next_available_date
}

// --- Submit -----------------------------------------------------------------

const submitting = ref(false)
const errors = ref<Record<string, string>>({})
const generalError = ref('')
const submitted = ref<OrderCreated | null>(null)

function flattenErrors(data: unknown): Record<string, string> {
  if (!data || typeof data !== 'object') return {}
  const result: Record<string, string> = {}
  for (const [field, value] of Object.entries(data as Record<string, unknown>)) {
    if (Array.isArray(value)) {
      const first = value.find((v) => typeof v === 'string')
      result[field] = first ?? t('order-errors__field--generic')
    } else if (typeof value === 'string') {
      result[field] = value
    } else {
      result[field] = t('order-errors__field--generic')
    }
  }
  return result
}

function validateLocally(): Record<string, string> {
  const found: Record<string, string> = {}
  if (!form.name.trim()) found.name = t('order-errors__name--required')
  if (!form.phone.trim()) found.phone = t('order-errors__phone--required')
  if (!consent.contact) found.contact_consent = t('order-errors__consent--required')
  if (form.zip_code && !zipComplete.value) found.zip_code = t('order-errors__zip--invalid')
  if (mode.value === 'delivery') {
    if (!form.delivery_address.trim()) found.delivery_address = t('order-errors__address--required')
    if (!form.zip_code) found.zip_code = t('order-errors__zip--required')
    if (selections.value.length === 0) found.items = t('order-errors__products--required')
    if (!form.preferred_date) found.preferred_date = t('order-errors__date--required')
    else if (!dateIsDeliveryDay.value) found.preferred_date = t('order-errors__date--no-delivery')
  } else if (!form.notes.trim()) {
    found.notes = t('order-errors__notes--required')
  }
  if (captchaRequired.value && !captchaToken.value) found.captcha_token = t('order-errors__captcha--required')
  return found
}

async function handleSubmit() {
  if (needsSpecialRequest.value) return setMode('callback')
  generalError.value = ''
  errors.value = validateLocally()
  if (Object.keys(errors.value).length) {
    requestAnimationFrame(() => document.querySelector('[data-error]')?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
    return
  }

  const isDelivery = mode.value === 'delivery'
  submitting.value = true
  try {
    submitted.value = await submitOrder({
      request_type: mode.value,
      name: form.name.trim(),
      phone: form.phone.trim(),
      email: form.email.trim(),
      delivery_address: form.delivery_address.trim(),
      zip_code: zip.value,
      // Special requests keep what they picked, so we know what they're after.
      items: selections.value,
      preferred_date: isDelivery ? form.preferred_date : null,
      delivery_window: form.delivery_window,
      placement_notes: form.placement_notes.trim(),
      notes: form.notes.trim(),
      contact_consent: consent.contact,
      marketing_consent: consent.marketing,
      website: form.website,
      captcha_token: captchaToken.value
    })
    clearTimeout(draftTimer)
    clearDraft()
    draftRestored.value = false
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 400) {
      errors.value = flattenErrors(error.response.data)
      generalError.value = errors.value.captcha_token || errors.value.detail || t('order-errors__summary')
      // Turnstile tokens are single-use; get a fresh one for the retry.
      captcha.value?.reset()
    } else if (axios.isAxiosError(error) && error.response?.status === 429) {
      generalError.value = t('order-errors__rate-limited', { phone: business.phone })
    } else {
      generalError.value = t('order-errors__generic', { phone: business.phone })
    }
  } finally {
    submitting.value = false
  }
}

function startOver() {
  submitted.value = null
  for (const key of Object.keys(selected)) delete selected[key]
  Object.assign(form, { preferred_date: defaultDate(), delivery_window: 'any', notes: '' })
  captchaToken.value = ''
  Object.assign(consent, { contact: false, marketing: false })
}

// "Order again" from an earlier order: same place, same products.
async function prefillFrom(id: string) {
  try {
    const previous = await fetchMyOrder(id)
    Object.assign(form, {
      delivery_address: previous.delivery_address,
      zip_code: previous.zip_code,
      placement_notes: previous.placement_notes
    })
    for (const key of Object.keys(selected)) delete selected[key]
    for (const item of previous.items) selected[item.key] = item.quantity
  } catch {
    // Not theirs or gone: start from the saved draft instead.
  }
}

async function loadCatalog() {
  try {
    catalog.value = await fetchCatalog()
    catalogError.value = false
    // Drop saved selections the catalog no longer offers.
    for (const [key, quantity] of Object.entries(selected)) {
      const p = product(key)
      if (!p) delete selected[key]
      else setYards(key, quantity)
    }
  } catch {
    catalogError.value = true
  }
}

onMounted(async () => {
  restoreDraft()
  if (authStore.isAuthenticated && !authStore.isStaff) {
    form.name ||= authStore.user?.name ?? ''
    form.email ||= authStore.user?.email ?? ''
    if (typeof route.query.from === 'string') await prefillFrom(route.query.from)
  }
  if (typeof route.query.product === 'string') selected[route.query.product] ||= 1
  await loadCatalog()
  if (!dateIsDeliveryDay.value) form.preferred_date = defaultDate()
})

watch(locale, loadCatalog)

// Phones get a bar pinned to the bottom of the viewport linking down to the
// full quote; once that quote scrolls into view the bar is redundant.
const quoteSection = ref<HTMLElement | null>(null)
const quoteSectionVisible = ref(false)
let quoteSectionObserver: IntersectionObserver | null = null

watch(quoteSection, (el) => {
  quoteSectionObserver?.disconnect()
  if (!el) return
  quoteSectionObserver = new IntersectionObserver(([entry]) => {
    quoteSectionVisible.value = entry.isIntersecting
  })
  quoteSectionObserver.observe(el)
})
onBeforeUnmount(() => quoteSectionObserver?.disconnect())

const inputClass =
  'mt-1 block w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-stone-900 shadow-sm placeholder:text-stone-400 focus:border-lime-600 focus:outline-none focus:ring-2 focus:ring-lime-500/40'
const labelClass = 'block text-sm font-medium text-stone-700'
const cardClass = 'rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200'
</script>

<template>
  <div class="flex flex-1 flex-col">
    <div class="mx-auto w-full max-w-6xl flex-1 px-4 py-10 sm:px-6">
      <!-- Confirmation -->
      <section v-if="submitted" class="order-confirmation mx-auto max-w-2xl rounded-3xl bg-white p-8 text-center shadow-sm ring-1 ring-stone-200">
        <div class="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
          <svg class="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 class="mt-5 text-2xl font-bold text-stone-900">
          {{ submitted.request_type === 'delivery' ? t('order-confirmation__title--delivery') : t('order-confirmation__title--callback') }}
        </h1>
        <p class="mt-3 text-stone-600">
          <template v-if="submitted.request_type === 'delivery'">
            {{ t('order-confirmation__body--delivery', { date: formatDate(submitted.preferred_date) }) }}
          </template>
          <template v-else>{{ t('order-confirmation__body--callback') }}</template>
        </p>
        <p v-if="submitted.plan_status === 'no_capacity' || submitted.plan_status === 'out_of_stock'" class="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200">
          {{ t(`order-confirmation__plan-note--${submitted.plan_status}`) }}
        </p>
        <p v-if="'total' in submitted.quote" class="mt-6 rounded-2xl bg-stone-50 p-4 text-stone-700">
          {{ t('order-confirmation__total-label') }}
          <span class="text-xl font-bold text-stone-900">{{ formatMoney(submitted.quote.total) }}</span>
          <span class="block text-xs text-stone-500">{{ t('order-confirmation__total-note') }}</span>
        </p>
        <div v-if="submitted.claim_token" class="mt-6 rounded-2xl bg-lime-50 p-5 text-left ring-1 ring-lime-200">
          <p class="font-semibold text-stone-900">{{ t('order-confirmation__claim-title') }}</p>
          <p class="mt-1 text-sm text-stone-700">{{ t('order-confirmation__claim-body') }}</p>
          <div class="mt-4 flex flex-col gap-2 sm:flex-row">
            <router-link
              :to="{ name: 'register', query: { redirect: `/claim/${submitted.claim_token}` } }"
              class="rounded-xl bg-stone-900 px-4 py-2 text-center text-sm font-semibold text-white hover:bg-stone-800"
            >
              {{ t('order-confirmation__claim-register') }}
            </router-link>
            <router-link
              :to="{ name: 'login', query: { redirect: `/claim/${submitted.claim_token}` } }"
              class="rounded-xl px-4 py-2 text-center text-sm font-semibold text-stone-700 ring-1 ring-stone-300 hover:bg-white"
            >
              {{ t('order-confirmation__claim-login') }}
            </router-link>
          </div>
        </div>
        <router-link
          v-else-if="authStore.isAuthenticated"
          :to="{ name: 'account-order', params: { id: submitted.id } }"
          class="mt-6 inline-block font-semibold text-lime-700 hover:text-lime-600"
        >
          {{ t('order-confirmation__orders-link') }} →
        </router-link>
        <p class="mt-6 text-sm text-stone-500">{{ t('order-confirmation__reference', { id: submitted.id, phone: business.phone }) }}</p>
        <div class="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
          <router-link :to="{ name: 'home' }" class="rounded-xl border border-stone-300 px-5 py-2.5 font-semibold text-stone-700 hover:bg-stone-50">
            {{ t('order-confirmation__home-link') }}
          </router-link>
          <button type="button" class="rounded-xl bg-stone-900 px-5 py-2.5 font-semibold text-white hover:bg-stone-800" @click="startOver">
            {{ t('order-confirmation__again') }}
          </button>
        </div>
      </section>

      <template v-else>
        <div class="order-header max-w-2xl">
          <h1 class="text-3xl font-bold tracking-tight text-stone-900">
            {{ mode === 'delivery' ? t('order-header__title--delivery') : t('order-header__title--callback') }}
          </h1>
          <p class="mt-2 text-stone-600">
            {{ mode === 'delivery' ? t('order-header__intro--delivery') : t('order-header__intro--callback') }}
          </p>
        </div>

        <p v-if="draftRestored" class="order-draft mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-sky-50 px-4 py-2.5 text-sm text-sky-900 ring-1 ring-sky-200" role="status">
          <span>{{ t('order-draft__restored') }}</span>
          <button type="button" class="font-semibold underline hover:text-sky-700" @click="clearForm">{{ t('order-draft__clear') }}</button>
        </p>

        <div class="order-mode mt-6 inline-flex rounded-xl bg-stone-200 p-1" role="tablist" :aria-label="t('order-mode__label')">
          <button
            v-for="option in (['delivery', 'callback'] as const)"
            :key="option"
            type="button"
            role="tab"
            :aria-selected="mode === option"
            class="rounded-lg px-4 py-2 text-sm font-semibold transition"
            :class="mode === option ? 'bg-white text-stone-900 shadow-sm' : 'text-stone-600 hover:text-stone-900'"
            @click="setMode(option)"
          >
            {{ t(`order-mode__tab--${option}`) }}
          </button>
        </div>

        <form class="mt-8 grid gap-8 lg:grid-cols-[1fr_22rem]" novalidate @submit.prevent="handleSubmit">
          <div class="space-y-8">
            <!-- Where -->
            <fieldset class="order-location" :class="cardClass">
              <legend class="sr-only">{{ t('order-location__title') }}</legend>
              <h2 class="text-lg font-semibold text-stone-900">{{ t('order-location__title') }}</h2>
              <div class="mt-4 grid gap-4 sm:grid-cols-[1fr_9rem]">
                <div>
                  <label for="delivery_address" :class="labelClass">
                    {{ t('order-location__address-label') }}
                    <span v-if="mode === 'callback'" class="font-normal text-stone-500">{{ t('order-form__optional') }}</span>
                  </label>
                  <input id="delivery_address" v-model="form.delivery_address" type="text" autocomplete="street-address" maxlength="255" :class="[inputClass, errors.delivery_address && 'border-red-400']" />
                  <p v-if="errors.delivery_address" data-error class="mt-1 text-sm text-red-600">{{ errors.delivery_address }}</p>
                </div>
                <div>
                  <label for="zip_code" :class="labelClass">{{ t('order-location__zip-label') }}</label>
                  <input
                    id="zip_code"
                    v-model="form.zip_code"
                    type="text"
                    inputmode="numeric"
                    autocomplete="postal-code"
                    maxlength="10"
                    :class="[inputClass, 'tracking-wider', errors.zip_code && 'border-red-400']"
                    :aria-invalid="!!errors.zip_code"
                  />
                </div>
              </div>
              <p v-if="errors.zip_code" data-error class="mt-2 text-sm text-red-600">{{ errors.zip_code }}</p>
              <p v-else-if="zipComplete && !plan && estimating" class="mt-2 text-sm text-stone-500">{{ t('order-location__status--checking') }}</p>
              <p v-else-if="coverage === 'serve'" class="mt-2 flex items-center gap-1.5 text-sm text-emerald-700">
                <span aria-hidden="true">✓</span>
                {{ plan?.city ? t('order-location__status--serve', { city: plan.city }) : t('order-location__status--serve-no-city') }}
              </p>
              <div v-else-if="coverage === 'contact' || coverage === 'outside'" class="mt-3 rounded-xl bg-amber-50 p-4 text-sm text-amber-900 ring-1 ring-amber-200">
                <p class="font-semibold">{{ t(`order-location__status-title--${coverage}`) }}</p>
                <p class="mt-1">{{ t(`order-location__status-body--${coverage}`) }}</p>
                <button v-if="mode === 'delivery'" type="button" class="mt-2 font-semibold underline" @click="setMode('callback')">
                  {{ t('order-location__special-request-link') }}
                </button>
              </div>
              <p v-else class="mt-2 text-xs text-stone-500">{{ t('order-location__zip-hint') }}</p>
            </fieldset>

            <!-- What -->
            <fieldset class="order-products" :class="cardClass">
              <legend class="sr-only">{{ t('order-products__title') }}</legend>
              <div class="flex flex-wrap items-baseline justify-between gap-2">
                <h2 class="text-lg font-semibold text-stone-900">
                  {{ t('order-products__title') }}
                  <span v-if="mode === 'callback'" class="text-sm font-normal text-stone-500">{{ t('order-form__optional') }}</span>
                </h2>
                <button type="button" class="text-sm font-semibold text-lime-700 hover:text-lime-600" :aria-expanded="calculator.open" @click="calculator.open = !calculator.open">
                  {{ t('order-calculator__toggle') }}
                </button>
              </div>
              <p class="mt-1 text-sm text-stone-500">{{ t('order-products__intro') }}</p>
              <p v-if="errors.items" data-error class="mt-2 text-sm text-red-600">{{ errors.items }}</p>

              <!-- How much do I need? -->
              <div v-if="calculator.open" class="order-calculator mt-4 rounded-xl bg-stone-50 p-4 ring-1 ring-stone-200">
                <p class="text-sm text-stone-600">{{ t('order-calculator__intro') }}</p>
                <div class="mt-3 grid grid-cols-3 gap-3">
                  <label class="text-xs font-medium text-stone-600">{{ t('order-calculator__length-label') }}
                    <input v-model="calculator.length" type="number" min="0" inputmode="decimal" :class="inputClass" />
                  </label>
                  <label class="text-xs font-medium text-stone-600">{{ t('order-calculator__width-label') }}
                    <input v-model="calculator.width" type="number" min="0" inputmode="decimal" :class="inputClass" />
                  </label>
                  <label class="text-xs font-medium text-stone-600">{{ t('order-calculator__depth-label') }}
                    <input v-model="calculator.depth" type="number" min="0" inputmode="decimal" :class="inputClass" />
                  </label>
                </div>
                <div class="mt-3 flex flex-wrap items-center gap-3">
                  <p class="text-sm font-semibold text-stone-900">
                    {{ calculatedYards ? t('order-calculator__result', { yards: calculatedYards }) : t('order-calculator__result--empty') }}
                  </p>
                  <template v-if="calculatedYards && catalog">
                    <select v-model="calculator.product" class="rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm" :aria-label="t('order-calculator__product-label')">
                      <option value="">{{ t('order-calculator__product-label') }}</option>
                      <option v-for="p in catalog.products" :key="p.key" :value="p.key">{{ p.name }}</option>
                    </select>
                    <button type="button" class="rounded-lg bg-stone-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-stone-800" @click="useCalculated">
                      {{ t('order-calculator__use') }}
                    </button>
                  </template>
                </div>
                <p class="mt-2 text-xs text-stone-500">{{ t('order-calculator__hint') }}</p>
              </div>

              <p v-if="catalogError" class="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-700">
                {{ t('order-products__load-error') }}
                <button type="button" class="font-semibold underline" @click="setMode('callback')">{{ t('order-products__load-error-link') }}</button>.
              </p>
              <div v-else-if="!catalog" class="mt-4 space-y-3">
                <div v-for="n in 5" :key="n" class="h-16 animate-pulse rounded-xl bg-stone-100" />
              </div>
              <ul v-else class="mt-4 space-y-3">
                <li
                  v-for="p in catalog.products"
                  :key="p.key"
                  class="rounded-xl border transition"
                  :class="selected[p.key] ? 'border-lime-500 bg-lime-50/60 ring-1 ring-lime-500' : 'border-stone-200 hover:border-stone-300'"
                >
                  <label class="flex cursor-pointer items-start gap-3 p-4">
                    <input type="checkbox" class="mt-1 h-5 w-5 rounded border-stone-300 accent-lime-600" :checked="!!selected[p.key]" @change="toggleProduct(p.key)" />
                    <span class="flex-1">
                      <span class="flex items-baseline justify-between gap-3">
                        <span class="font-medium text-stone-900">{{ p.name }}</span>
                        <span class="whitespace-nowrap text-sm font-semibold text-stone-900">
                          {{ formatMoney(p.price_per_yard) }}<span class="font-normal text-stone-500">/{{ t('order-products__unit') }}</span>
                        </span>
                      </span>
                      <span class="mt-0.5 block text-sm text-stone-500">{{ p.description }}</span>
                      <span v-if="p.min_yards > 1" class="mt-0.5 block text-xs font-medium text-stone-500">{{ t('order-products__minimum', { min: p.min_yards }) }}</span>
                    </span>
                  </label>
                  <div v-if="selected[p.key]" class="flex flex-wrap items-center gap-2 border-t border-lime-200 px-4 py-3 sm:pl-12">
                    <span class="text-sm text-stone-600">{{ t('order-products__quantity-label') }}</span>
                    <button type="button" class="h-9 w-9 rounded-lg bg-white text-lg font-semibold ring-1 ring-stone-300 hover:bg-stone-50 disabled:opacity-40" :disabled="selected[p.key] <= p.min_yards" :aria-label="t('order-products__decrease', { product: p.name })" @click="setYards(p.key, selected[p.key] - 1)">−</button>
                    <input
                      type="number"
                      :min="p.min_yards"
                      :max="p.max_yards"
                      :value="selected[p.key]"
                      class="w-20 rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-center font-semibold"
                      :aria-label="t('order-products__quantity-input', { product: p.name })"
                      @change="setYards(p.key, Number(($event.target as HTMLInputElement).value))"
                    />
                    <button type="button" class="h-9 w-9 rounded-lg bg-white text-lg font-semibold ring-1 ring-stone-300 hover:bg-stone-50 disabled:opacity-40" :disabled="selected[p.key] >= p.max_yards" :aria-label="t('order-products__increase', { product: p.name })" @click="setYards(p.key, selected[p.key] + 1)">+</button>
                    <span class="ml-auto text-sm font-medium text-stone-700">{{ formatMoney(Number(p.price_per_yard) * selected[p.key]) }}</span>
                  </div>
                </li>
              </ul>
              <ul v-if="stockProblems.length && mode === 'delivery'" class="mt-3 space-y-1">
                <li v-for="problem in stockProblems" :key="problem.product" class="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">
                  {{ t('order-products__out-of-stock', { product: problem.product_name }) }}
                </li>
              </ul>
            </fieldset>

            <!-- When -->
            <fieldset v-if="mode === 'delivery'" class="order-date" :class="cardClass">
              <legend class="sr-only">{{ t('order-date__title') }}</legend>
              <h2 class="text-lg font-semibold text-stone-900">{{ t('order-date__title') }}</h2>
              <p class="mt-1 text-sm text-stone-500">{{ t('order-date__intro') }}</p>
              <div class="mt-3 flex flex-wrap items-end gap-4">
                <input
                  id="preferred_date"
                  v-model="form.preferred_date"
                  type="date"
                  :min="minDate"
                  :max="maxDate"
                  :class="[inputClass, 'max-w-xs', (errors.preferred_date || !dateIsDeliveryDay) && 'border-red-400']"
                  :aria-label="t('order-date__title')"
                />
                <div class="flex rounded-xl bg-stone-100 p-1" role="radiogroup" :aria-label="t('order-date__window-label')">
                  <button
                    v-for="window in DELIVERY_WINDOWS"
                    :key="window"
                    type="button"
                    role="radio"
                    :aria-checked="form.delivery_window === window"
                    class="rounded-lg px-3 py-1.5 text-sm font-medium"
                    :class="form.delivery_window === window ? 'bg-white text-stone-900 shadow-sm' : 'text-stone-600 hover:text-stone-900'"
                    @click="form.delivery_window = window"
                  >
                    {{ t(`order-date__window--${window}`) }}
                  </button>
                </div>
              </div>
              <p v-if="errors.preferred_date" data-error class="mt-1 text-sm text-red-600">{{ errors.preferred_date }}</p>
              <p v-else-if="!dateIsDeliveryDay" class="mt-1 text-sm text-red-600">{{ t('order-errors__date--no-delivery') }}</p>

              <div v-if="plan?.status === 'no_capacity'" class="mt-4 rounded-xl bg-amber-50 p-4 text-sm text-amber-900 ring-1 ring-amber-200">
                <p class="font-semibold">{{ t('order-date__full-title') }}</p>
                <p class="mt-1">
                  {{ plan.next_available_date ? t('order-date__full-body', { date: formatDate(plan.next_available_date) }) : t('order-date__full-body--no-date') }}
                </p>
                <button v-if="plan.next_available_date" type="button" class="mt-2 font-semibold underline" @click="useNextDate">
                  {{ t('order-date__use-next', { date: formatDate(plan.next_available_date) }) }}
                </button>
              </div>
              <div v-else-if="isRush && catalog" class="mt-4 rounded-xl bg-orange-50 p-4 text-sm text-orange-900 ring-1 ring-orange-200">
                <p class="font-semibold">{{ t('order-date__rush-title') }}</p>
                <p class="mt-1">{{ t('order-date__rush-body', { fee: formatMoney(catalog.rush_fee) }) }}</p>
              </div>
            </fieldset>

            <!-- Drop spot -->
            <fieldset v-if="mode === 'delivery'" class="order-placement" :class="cardClass">
              <legend class="sr-only">{{ t('order-placement__title') }}</legend>
              <h2 class="text-lg font-semibold text-stone-900">{{ t('order-placement__title') }}</h2>
              <textarea
                id="placement_notes"
                v-model="form.placement_notes"
                rows="3"
                maxlength="2000"
                :placeholder="t('order-placement__placeholder')"
                :class="inputClass"
                :aria-label="t('order-placement__title')"
              />
              <ul class="mt-3 space-y-1 text-xs text-stone-500">
                <li v-for="n in 3" :key="n">• {{ t(`order-placement__tip--${n}`) }}</li>
              </ul>
            </fieldset>

            <!-- Contact -->
            <fieldset class="order-contact" :class="cardClass">
              <legend class="sr-only">{{ t('order-contact__title') }}</legend>
              <h2 class="text-lg font-semibold text-stone-900">{{ t('order-contact__title') }}</h2>
              <div class="mt-4 grid gap-4 sm:grid-cols-2">
                <div class="sm:col-span-2">
                  <label for="name" :class="labelClass">{{ t('order-contact__name-label') }}</label>
                  <input id="name" v-model="form.name" type="text" autocomplete="name" maxlength="120" :class="[inputClass, errors.name && 'border-red-400']" />
                  <p v-if="errors.name" data-error class="mt-1 text-sm text-red-600">{{ errors.name }}</p>
                </div>
                <div>
                  <label for="phone" :class="labelClass">{{ t('order-contact__phone-label') }}</label>
                  <input id="phone" v-model="form.phone" type="tel" autocomplete="tel" maxlength="32" :class="[inputClass, errors.phone && 'border-red-400']" />
                </div>
                <div>
                  <label for="email" :class="labelClass">
                    {{ t('order-contact__email-label') }}
                    <span class="font-normal text-stone-500">{{ t('order-form__optional') }}</span>
                  </label>
                  <input id="email" v-model="form.email" type="email" autocomplete="email" :class="[inputClass, errors.email && 'border-red-400']" />
                  <p v-if="errors.email" data-error class="mt-1 text-sm text-red-600">{{ errors.email }}</p>
                </div>
                <p v-if="errors.phone" data-error class="text-sm text-red-600 sm:col-span-2">{{ errors.phone }}</p>
                <div class="sm:col-span-2">
                  <label for="notes" :class="labelClass">
                    {{ t(`order-contact__notes-label--${mode}`) }}
                    <span v-if="mode === 'delivery'" class="font-normal text-stone-500">{{ t('order-form__optional') }}</span>
                  </label>
                  <textarea
                    id="notes"
                    v-model="form.notes"
                    :rows="mode === 'delivery' ? 3 : 5"
                    maxlength="4000"
                    :placeholder="t(`order-contact__notes-placeholder--${mode}`)"
                    :class="[inputClass, errors.notes && 'border-red-400']"
                  />
                  <p v-if="errors.notes" data-error class="mt-1 text-sm text-red-600">{{ errors.notes }}</p>
                </div>
                <div class="order-consent space-y-3 rounded-xl bg-stone-50 p-4 sm:col-span-2">
                  <label class="flex items-start gap-3 text-sm text-stone-800">
                    <input id="contact_consent" v-model="consent.contact" type="checkbox" class="mt-0.5 h-4 w-4 shrink-0 accent-lime-600" :aria-invalid="!!errors.contact_consent" />
                    <span>
                      {{ t('order-consent__contact') }}
                      <span class="text-red-600" aria-hidden="true">*</span>
                    </span>
                  </label>
                  <p v-if="errors.contact_consent" data-error class="text-sm text-red-600">{{ errors.contact_consent }}</p>
                  <label class="flex items-start gap-3 text-sm text-stone-800">
                    <input id="marketing_consent" v-model="consent.marketing" type="checkbox" class="mt-0.5 h-4 w-4 shrink-0 accent-lime-600" />
                    <span>
                      {{ t('order-consent__marketing') }}
                      <span class="block text-stone-500">{{ t('order-consent__marketing-promise') }}</span>
                    </span>
                  </label>
                </div>
              </div>
            </fieldset>
          </div>

          <!-- Quote sidebar -->
          <aside id="quote" ref="quoteSection" class="order-quote relative scroll-mt-20 pb-16 lg:sticky lg:top-24 lg:self-start lg:pb-0">
            <div class="rounded-2xl bg-stone-900 p-6 text-white shadow-lg">
              <template v-if="mode === 'delivery' && !needsSpecialRequest">
                <h2 class="text-lg font-semibold">{{ t('order-quote__title') }}</h2>
                <p v-if="!zipComplete" class="mt-3 text-sm text-stone-400">{{ t('order-quote__empty--zip') }}</p>
                <p v-else-if="selections.length === 0" class="mt-3 text-sm text-stone-400">{{ t('order-quote__empty--products') }}</p>
                <div v-else-if="quote" class="mt-4" :class="estimating && 'opacity-60'">
                  <QuoteBreakdown :quote="quote" dark />
                  <p class="mt-3 text-xs text-stone-400">
                    {{ t('order-quote__loads', quote.load_count) }}
                    <template v-if="shipsFrom.length"> {{ t('order-quote__ships-from', { yards: shipsFrom.join(', ') }) }}</template>
                  </p>
                </div>
                <p v-else-if="estimating" class="mt-3 text-sm text-stone-400">{{ t('order-quote__calculating') }}</p>
                <p v-else class="mt-3 text-sm text-stone-400">{{ t('order-quote__error') }}</p>

                <ul v-if="catalog" class="mt-5 space-y-2 border-t border-stone-700 pt-4 text-xs text-stone-400">
                  <li>{{ t('order-quote__note--delivery-fee', { fee: formatMoney(catalog.delivery_base_fee), miles: catalog.included_miles, perMile: formatMoney(catalog.per_mile_fee) }) }}</li>
                  <li>{{ t('order-quote__note--confirm') }}</li>
                </ul>
              </template>
              <template v-else-if="needsSpecialRequest">
                <h2 class="text-lg font-semibold">{{ t(`order-location__status-title--${coverage}`) }}</h2>
                <p class="mt-3 text-sm text-stone-300">{{ t('order-quote__special-body') }}</p>
              </template>
              <template v-else>
                <h2 class="text-lg font-semibold">{{ t('order-quote__callback-title') }}</h2>
                <p class="mt-3 text-sm text-stone-300">{{ t('order-quote__callback-body') }}</p>
                <a :href="phoneHref()" class="mt-3 inline-block font-semibold text-lime-400 hover:text-lime-300">{{ business.phone }}</a>
              </template>

              <div class="absolute -left-[9999px] h-px w-px overflow-hidden" aria-hidden="true">
                <label for="website">{{ t('order-form__honeypot-label') }}</label>
                <input id="website" v-model="form.website" type="text" name="website" tabindex="-1" autocomplete="off" />
              </div>
              <TurnstileWidget v-if="captchaRequired && !needsSpecialRequest" ref="captcha" class="mt-5" @update:token="captchaToken = $event" />

              <p v-if="generalError" class="mt-5 rounded-lg bg-red-500/15 p-3 text-sm text-red-200">{{ generalError }}</p>
              <button
                type="submit"
                :disabled="submitting"
                class="mt-5 w-full rounded-xl bg-lime-500 px-5 py-3 font-semibold text-stone-900 hover:bg-lime-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <template v-if="submitting">{{ t('order-quote__submit--sending') }}</template>
                <template v-else-if="needsSpecialRequest">{{ t('order-location__special-request-link') }}</template>
                <template v-else>{{ t(`order-quote__submit--${mode}`) }}</template>
              </button>
              <p v-if="mode === 'delivery' && !needsSpecialRequest" class="mt-3 text-center text-xs text-stone-400">{{ t('order-quote__no-payment') }}</p>
            </div>
          </aside>

          <!-- Phones: keep the running total visible; the full quote sits at the bottom. -->
          <a
            v-if="mode === 'delivery' && quote && !quoteSectionVisible"
            href="#quote"
            class="order-mobile-total fixed inset-x-0 bottom-0 z-20 flex items-center justify-between border-t border-stone-700 bg-stone-900 px-4 py-3 text-white lg:hidden"
          >
            <span class="text-sm text-stone-300">{{ t('quote-breakdown__total') }}</span>
            <span class="text-lg font-bold text-lime-400">
              {{ formatMoney(quote.total) }}
              <span class="ml-1 text-xs font-medium text-stone-400">{{ t('order-mobile-total__details-link') }} ↓</span>
            </span>
          </a>
        </form>
      </template>
    </div>
  </div>
</template>
