<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import axios from 'axios'
import TurnstileWidget from '@/components/TurnstileWidget.vue'
import PartsEstimateCard from '@/components/PartsEstimateCard.vue'
import { usePartsEstimate } from '@/composables/usePartsEstimate'
import { useAuthStore } from '@/stores/auth'
import { fetchMyRequest, fetchMyVehicles } from '@/services/garage'
import type { Vehicle } from '@/types/garage'
import { business, phoneHref } from '@/config/business'
import {
  decodeVin,
  fetchCatalog,
  fetchEstimate,
  fetchGuestPartsEstimate,
  submitServiceRequest
} from '@/services/intake'
import { VIN_PATTERN, formatDate, formatMoney, isoDateFromToday, normalizeVin } from '@/utils/intake'
import { DRAFT_FIELDS, clearDraft, isEmptyDraft, loadDraft, saveDraft } from '@/utils/intakeDraft'
import type {
  Catalog,
  Estimate,
  RequestType,
  ServiceRequestCreated,
  ServiceSelection,
  VehicleType
} from '@/types/intake'

// Text keys follow the form's sections: intake-header__*, intake-vehicle__*,
// intake-services__*, intake-date__*, intake-contact__*, intake-estimate__*,
// intake-confirmation__*, intake-errors__*.
const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const mode = computed<RequestType>(() => (route.query.mode === 'callback' ? 'callback' : 'booking'))

function setMode(next: RequestType) {
  router.replace({ query: next === 'callback' ? { mode: 'callback' } : {} })
  errors.value = {}
}

const catalog = ref<Catalog | null>(null)
const catalogError = ref(false)

const form = reactive({
  name: '',
  phone: '',
  email: '',
  service_address: '',
  vin: '',
  vehicle_year: '',
  vehicle_make: '',
  vehicle_model: '',
  vehicle_type: '' as VehicleType | '',
  other_description: '',
  preferred_date: isoDateFromToday(14),
  notes: '',
  // Honeypot: hidden from people, bots tend to fill it in.
  website: ''
})

// --- Accounts & spam protection ---------------------------------------------

const garage = ref<Vehicle[]>([])
const captchaToken = ref('')
const captcha = ref<InstanceType<typeof TurnstileWidget> | null>(null)
const captchaRequired = computed(
  () => !!import.meta.env.VITE_TURNSTILE_SITE_KEY && !authStore.isAuthenticated
)

function useVehicle(vehicle: Vehicle) {
  form.vin = vehicle.vin
  form.vehicle_year = vehicle.year
  form.vehicle_make = vehicle.make
  form.vehicle_model = vehicle.model
}

// Selected services: key -> quantity (axles for brake/suspension work).
const selected = reactive<Record<string, number>>({})

const selections = computed<ServiceSelection[]>(() =>
  Object.entries(selected).map(([key, quantity]) => ({ key, quantity }))
)

function toggleService(key: string) {
  if (selected[key]) {
    delete selected[key]
  } else {
    selected[key] = 1
  }
}

const minDate = isoDateFromToday(0)

// --- Draft ------------------------------------------------------------------
// The form is saved in this browser as it's filled in (see utils/intakeDraft),
// so a refresh or a detour to another page doesn't lose it.

const draftRestored = ref(false)
let draftTimer: ReturnType<typeof setTimeout> | undefined

function currentDraft() {
  return {
    form: Object.fromEntries(DRAFT_FIELDS.map((field) => [field, form[field]])),
    selected: { ...selected }
  }
}

function persistDraft() {
  clearTimeout(draftTimer)
  // Once sent, the form isn't a draft any more.
  if (submitted.value) return
  const draft = currentDraft()
  if (isEmptyDraft(draft, { preferred_date: isoDateFromToday(14) })) {
    clearDraft()
  } else {
    saveDraft(draft)
  }
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
  draftRestored.value = !isEmptyDraft(currentDraft(), { preferred_date: isoDateFromToday(14) })
}

function clearForm() {
  startOver()
  Object.assign(form, { name: '', phone: '', email: '', service_address: '' })
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

// --- VIN ------------------------------------------------------------------

const vinStatus = ref<'idle' | 'decoding' | 'decoded' | 'unknown'>('idle')
const vinValid = computed(() => VIN_PATTERN.test(normalizeVin(form.vin)))
let lastDecodedVin = ''

watch(
  () => form.vin,
  async (value) => {
    const vin = normalizeVin(value)
    if (!VIN_PATTERN.test(vin) || vin === lastDecodedVin) {
      if (!VIN_PATTERN.test(vin)) vinStatus.value = 'idle'
      return
    }
    lastDecodedVin = vin
    vinStatus.value = 'decoding'
    const vehicle = await decodeVin(vin)
    if (normalizeVin(form.vin) !== vin) return
    if (vehicle) {
      form.vehicle_year = vehicle.year
      form.vehicle_make = vehicle.make
      form.vehicle_model = vehicle.model
      vinStatus.value = 'decoded'
    } else {
      vinStatus.value = 'unknown'
    }
  }
)

// --- Live estimate ----------------------------------------------------------

const estimate = ref<Estimate | null>(null)
const estimating = ref(false)
let estimateTimer: ReturnType<typeof setTimeout> | undefined
let estimateRequest = 0

watch(
  // Re-fetch on language change too: line item names come from the API. The
  // vehicle type alone (no VIN needed) is enough to preview a parts estimate.
  [selections, () => form.preferred_date, () => form.vehicle_type, mode, locale],
  () => {
    clearTimeout(estimateTimer)
    if (mode.value !== 'booking' || selections.value.length === 0) {
      estimate.value = null
      return
    }
    estimating.value = true
    estimateTimer = setTimeout(async () => {
      const requestId = ++estimateRequest
      try {
        const result = await fetchEstimate(selections.value, form.preferred_date || null, form.vehicle_type)
        if (requestId === estimateRequest) estimate.value = result
      } catch {
        if (requestId === estimateRequest) estimate.value = null
      } finally {
        if (requestId === estimateRequest) estimating.value = false
      }
    }, 250)
  },
  { deep: true }
)

onBeforeUnmount(() => clearTimeout(estimateTimer))

const scheduling = computed(() => {
  if (!form.preferred_date || !catalog.value) return null
  const today = new Date(`${minDate}T00:00:00`)
  const chosen = new Date(`${form.preferred_date}T00:00:00`)
  const daysOut = Math.round((chosen.getTime() - today.getTime()) / 86_400_000)
  return {
    daysOut,
    isEmergency: daysOut < catalog.value.emergency_window_days,
    shortNotice: daysOut < catalog.value.booking_lead_days
  }
})

// --- Submit -----------------------------------------------------------------

const submitting = ref(false)
const errors = ref<Record<string, string>>({})
const generalError = ref('')
const submitted = ref<ServiceRequestCreated | null>(null)

// Parts are estimated server-side after booking; poll until ready.
const partsEstimate = usePartsEstimate(async () => {
  const created = submitted.value
  if (!created) return null
  if (created.claim_token) return fetchGuestPartsEstimate(created.claim_token)
  return (await fetchMyRequest(created.id)).parts_estimate
})
const submittedVehicle = ref('')

function flattenErrors(data: unknown): Record<string, string> {
  if (!data || typeof data !== 'object') return {}
  const result: Record<string, string> = {}
  for (const [field, value] of Object.entries(data as Record<string, unknown>)) {
    if (Array.isArray(value)) {
      const first = value.find((v) => typeof v === 'string')
      result[field] = first ?? t('intake-errors__field--generic')
    } else if (typeof value === 'string') {
      result[field] = value
    } else {
      result[field] = t('intake-errors__field--generic')
    }
  }
  return result
}

function validateLocally(): Record<string, string> {
  const found: Record<string, string> = {}
  if (!form.name.trim()) found.name = t('intake-errors__name--required')
  if (!form.phone.trim() && !form.email.trim()) found.phone = t('intake-errors__contact--required')
  const vin = normalizeVin(form.vin)
  if (mode.value === 'booking') {
    if (!vin) found.vin = t('intake-errors__vin--required')
    if (selections.value.length === 0) found.services = t('intake-errors__services--required')
    if (!form.preferred_date) found.preferred_date = t('intake-errors__date--required')
    if (selected.other && !form.other_description.trim()) {
      found.other_description = t('intake-errors__other--required')
    }
  } else if (!form.notes.trim()) {
    found.notes = t('intake-errors__notes--required')
  }
  if (vin && !VIN_PATTERN.test(vin)) found.vin = t('intake-errors__vin--invalid')
  if (captchaRequired.value && !captchaToken.value) found.captcha_token = t('intake-errors__captcha--required')
  return found
}

async function handleSubmit() {
  generalError.value = ''
  errors.value = validateLocally()
  if (Object.keys(errors.value).length) {
    requestAnimationFrame(() => document.querySelector('[data-error]')?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
    return
  }

  const isBooking = mode.value === 'booking'
  submitting.value = true
  try {
    submitted.value = await submitServiceRequest({
      request_type: mode.value,
      name: form.name.trim(),
      phone: form.phone.trim(),
      email: form.email.trim(),
      service_address: form.service_address.trim(),
      vin: normalizeVin(form.vin),
      vehicle_year: form.vehicle_year.trim(),
      vehicle_make: form.vehicle_make.trim(),
      vehicle_model: form.vehicle_model.trim(),
      vehicle_type: form.vehicle_type,
      services: isBooking ? selections.value : [],
      other_description: isBooking && selected.other ? form.other_description.trim() : '',
      preferred_date: isBooking ? form.preferred_date : null,
      notes: form.notes.trim(),
      website: form.website,
      captcha_token: captchaToken.value
    })
    submittedVehicle.value = [form.vehicle_year, form.vehicle_make, form.vehicle_model].filter(Boolean).join(' ')
    clearTimeout(draftTimer)
    clearDraft()
    draftRestored.value = false
    if (submitted.value.parts_estimate_status === 'pending') partsEstimate.start({ status: 'pending' })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 400) {
      errors.value = flattenErrors(error.response.data)
      generalError.value =
        errors.value.captcha_token || errors.value.detail || t('intake-errors__summary')
      // Turnstile tokens are single-use; get a fresh one for the retry.
      captcha.value?.reset()
    } else if (axios.isAxiosError(error) && error.response?.status === 429) {
      generalError.value = t('intake-errors__rate-limited', { phone: business.phone })
    } else {
      generalError.value = t('intake-errors__generic', { phone: business.phone })
    }
  } finally {
    submitting.value = false
  }
}

function startOver() {
  submitted.value = null
  partsEstimate.stop()
  partsEstimate.estimate.value = null
  for (const key of Object.keys(selected)) delete selected[key]
  Object.assign(form, {
    vin: '',
    vehicle_year: '',
    vehicle_make: '',
    vehicle_model: '',
    vehicle_type: '',
    other_description: '',
    preferred_date: isoDateFromToday(14),
    notes: ''
  })
  lastDecodedVin = ''
  vinStatus.value = 'idle'
  captchaToken.value = ''
}

onMounted(async () => {
  restoreDraft()
  if (typeof route.query.vin === 'string') form.vin = route.query.vin

  if (authStore.isAuthenticated && !authStore.isStaff) {
    form.name ||= authStore.user?.name ?? ''
    form.email ||= authStore.user?.email ?? ''
    fetchMyVehicles()
      .then((vehicles) => {
        garage.value = vehicles
        const match = vehicles.find((v) => v.vin === normalizeVin(form.vin))
        if (match) useVehicle(match)
      })
      .catch(() => {})
  }

  await loadCatalog()
})

async function loadCatalog() {
  try {
    catalog.value = await fetchCatalog()
    catalogError.value = false
    // Drop saved selections the catalog no longer offers.
    for (const [key, quantity] of Object.entries(selected)) {
      const service = catalog.value.services.find((s) => s.key === key)
      if (!service) delete selected[key]
      else if (quantity > service.max_quantity) selected[key] = service.max_quantity
    }
  } catch {
    catalogError.value = true
  }
}

watch(locale, loadCatalog)

const inputClass =
  'mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-400/40'
const labelClass = 'block text-sm font-medium text-slate-700'
</script>

<template>
  <div class="flex flex-1 flex-col">

    <div class="mx-auto w-full max-w-6xl flex-1 px-4 py-10 sm:px-6">
      <!-- Confirmation -->
      <section v-if="submitted" class="intake-confirmation mx-auto max-w-2xl rounded-3xl bg-white p-8 text-center shadow-sm ring-1 ring-slate-200">
        <div class="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
          <svg class="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 class="mt-5 text-2xl font-bold text-slate-900">
          {{ submitted.request_type === 'booking' ? t('intake-confirmation__title--booking') : t('intake-confirmation__title--callback') }}
        </h1>
        <p class="mt-3 text-slate-600">
          <template v-if="submitted.request_type === 'booking'">
            {{ submitted.preferred_date
              ? t('intake-confirmation__body--booking-date', { date: formatDate(submitted.preferred_date) })
              : t('intake-confirmation__body--booking') }}
          </template>
          <template v-else>{{ t('intake-confirmation__body--callback') }}</template>
        </p>
        <p
          v-if="submitted.request_type === 'booking' && 'total' in submitted.estimate"
          class="mt-6 rounded-2xl bg-slate-50 p-4 text-slate-700"
        >
          {{ t('intake-confirmation__labor-label') }}
          <span class="text-xl font-bold text-slate-900">{{ formatMoney(submitted.estimate.total) }}</span>
          <span class="block text-xs text-slate-500">{{ t('intake-confirmation__labor-note') }}</span>
        </p>
        <div v-if="partsEstimate.estimate.value" class="mt-4 rounded-2xl bg-white p-4 text-left ring-1 ring-slate-200">
          <PartsEstimateCard
            :estimate="partsEstimate.estimate.value"
            :labor-total="'total' in submitted.estimate ? submitted.estimate.total : null"
            :vehicle-label="submittedVehicle"
          />
        </div>
        <div v-if="submitted.claim_token" class="mt-6 rounded-2xl bg-amber-50 p-5 text-left ring-1 ring-amber-200">
          <p class="font-semibold text-slate-900">{{ t('intake-confirmation__claim-title') }}</p>
          <p class="mt-1 text-sm text-slate-700">{{ t('intake-confirmation__claim-body') }}</p>
          <div class="mt-4 flex flex-col gap-2 sm:flex-row">
            <router-link
              :to="{ name: 'register', query: { redirect: `/claim/${submitted.claim_token}` } }"
              class="rounded-xl bg-slate-900 px-4 py-2 text-center text-sm font-semibold text-white hover:bg-slate-800"
            >
              {{ t('intake-confirmation__claim-register') }}
            </router-link>
            <router-link
              :to="{ name: 'login', query: { redirect: `/claim/${submitted.claim_token}` } }"
              class="rounded-xl px-4 py-2 text-center text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-white"
            >
              {{ t('intake-confirmation__claim-login') }}
            </router-link>
          </div>
        </div>
        <router-link
          v-else-if="authStore.isAuthenticated"
          :to="{ name: 'account-request', params: { id: submitted.id } }"
          class="mt-6 inline-block font-semibold text-amber-700 hover:text-amber-600"
        >
          {{ t('intake-confirmation__garage-link') }} →
        </router-link>
        <p class="mt-6 text-sm text-slate-500">{{ t('intake-confirmation__reference', { id: submitted.id, phone: business.phone }) }}</p>
        <div class="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
          <router-link :to="{ name: 'home' }" class="rounded-xl border border-slate-300 px-5 py-2.5 font-semibold text-slate-700 hover:bg-slate-50">
            {{ t('intake-confirmation__home-link') }}
          </router-link>
          <button type="button" class="rounded-xl bg-slate-900 px-5 py-2.5 font-semibold text-white hover:bg-slate-800" @click="startOver">
            {{ t('intake-confirmation__again') }}
          </button>
        </div>
      </section>

      <template v-else>
        <div class="intake-header max-w-2xl">
          <h1 class="text-3xl font-bold tracking-tight text-slate-900">
            {{ mode === 'booking' ? t('intake-header__title--booking') : t('intake-header__title--callback') }}
          </h1>
          <p class="mt-2 text-slate-600">
            {{ mode === 'booking' ? t('intake-header__intro--booking') : t('intake-header__intro--callback') }}
          </p>
        </div>

        <p v-if="draftRestored" class="intake-draft mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-sky-50 px-4 py-2.5 text-sm text-sky-900 ring-1 ring-sky-200" role="status">
          <span>{{ t('intake-draft__restored') }}</span>
          <button type="button" class="font-semibold underline hover:text-sky-700" @click="clearForm">{{ t('intake-draft__clear') }}</button>
        </p>

        <div class="intake-mode mt-6 inline-flex rounded-xl bg-slate-200 p-1" role="tablist" :aria-label="t('intake-mode__label')">
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'booking'"
            class="rounded-lg px-4 py-2 text-sm font-semibold transition"
            :class="mode === 'booking' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'"
            @click="setMode('booking')"
          >
            {{ t('intake-mode__tab--booking') }}
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'callback'"
            class="rounded-lg px-4 py-2 text-sm font-semibold transition"
            :class="mode === 'callback' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'"
            @click="setMode('callback')"
          >
            {{ t('intake-mode__tab--callback') }}
          </button>
        </div>

        <form class="mt-8 grid gap-8 lg:grid-cols-[1fr_22rem]" novalidate @submit.prevent="handleSubmit">
          <div class="space-y-8">
            <!-- Vehicle -->
            <fieldset class="intake-vehicle rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
              <legend class="sr-only">{{ t('intake-vehicle__title') }}</legend>
              <h2 class="text-lg font-semibold text-slate-900">
                {{ t('intake-vehicle__title') }}
                <span v-if="mode === 'callback'" class="text-sm font-normal text-slate-500">{{ t('intake-form__optional') }}</span>
              </h2>
              <div v-if="garage.length" class="mt-3 flex flex-wrap gap-2">
                <span class="w-full text-sm text-slate-500">{{ t('intake-vehicle__garage-label') }}</span>
                <button
                  v-for="vehicle in garage"
                  :key="vehicle.id"
                  type="button"
                  class="rounded-full px-3 py-1.5 text-sm font-medium ring-1"
                  :class="normalizeVin(form.vin) === vehicle.vin ? 'bg-slate-900 text-white ring-slate-900' : 'bg-white text-slate-700 ring-slate-300 hover:bg-slate-50'"
                  @click="useVehicle(vehicle)"
                >
                  {{ vehicle.label }}
                </button>
              </div>
              <div class="mt-4">
                <label for="vin" :class="labelClass">{{ t('intake-vehicle__vin-label') }}</label>
                <input
                  id="vin"
                  v-model="form.vin"
                  type="text"
                  inputmode="text"
                  autocomplete="off"
                  autocapitalize="characters"
                  spellcheck="false"
                  maxlength="20"
                  :placeholder="t('intake-vehicle__vin-placeholder')"
                  :class="[inputClass, 'font-mono uppercase tracking-wider', errors.vin && 'border-red-400']"
                  :aria-invalid="!!errors.vin"
                />
                <p v-if="errors.vin" data-error class="mt-1 text-sm text-red-600">{{ errors.vin }}</p>
                <p v-else-if="vinStatus === 'decoding'" class="mt-1 text-sm text-slate-500">{{ t('intake-vehicle__vin-status--decoding') }}</p>
                <p v-else-if="vinStatus === 'decoded'" class="mt-1 text-sm text-emerald-700">
                  {{ t('intake-vehicle__vin-status--decoded', { vehicle: [form.vehicle_year, form.vehicle_make, form.vehicle_model].filter(Boolean).join(' ') }) }}
                </p>
                <p v-else-if="vinStatus === 'unknown'" class="mt-1 text-sm text-slate-500">
                  {{ t('intake-vehicle__vin-status--unknown') }}
                </p>
                <p v-else-if="form.vin && !vinValid" class="mt-1 text-sm text-slate-500">
                  {{ t('intake-vehicle__vin-status--count', { count: normalizeVin(form.vin).length }) }}
                </p>
                <p v-else class="mt-1 text-xs text-slate-500">
                  {{ t('intake-vehicle__vin-hint') }}
                </p>
              </div>
              <div class="mt-4 grid grid-cols-[6rem_1fr_1fr] gap-3">
                <div>
                  <label for="vehicle_year" :class="labelClass">{{ t('intake-vehicle__year-label') }}</label>
                  <input id="vehicle_year" v-model="form.vehicle_year" type="text" inputmode="numeric" maxlength="4" :class="inputClass" />
                </div>
                <div>
                  <label for="vehicle_make" :class="labelClass">{{ t('intake-vehicle__make-label') }}</label>
                  <input id="vehicle_make" v-model="form.vehicle_make" type="text" maxlength="60" :class="inputClass" />
                </div>
                <div>
                  <label for="vehicle_model" :class="labelClass">{{ t('intake-vehicle__model-label') }}</label>
                  <input id="vehicle_model" v-model="form.vehicle_model" type="text" maxlength="60" :class="inputClass" />
                </div>
              </div>
              <div v-if="mode === 'booking'" class="mt-4">
                <label for="vehicle_type" :class="labelClass">
                  {{ t('intake-vehicle__type-label') }}
                  <span class="font-normal text-slate-500">{{ t('intake-form__optional') }}</span>
                </label>
                <select id="vehicle_type" v-model="form.vehicle_type" :class="[inputClass, 'bg-white']">
                  <option value="">{{ t('intake-vehicle__type-placeholder') }}</option>
                  <option v-for="type in catalog?.vehicle_types" :key="type.key" :value="type.key">{{ type.label }}</option>
                </select>
                <p class="mt-1 text-xs text-slate-500">{{ t('intake-vehicle__type-hint') }}</p>
              </div>
            </fieldset>

            <!-- Services -->
            <fieldset v-if="mode === 'booking'" class="intake-services rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
              <legend class="sr-only">{{ t('intake-services__title') }}</legend>
              <h2 class="text-lg font-semibold text-slate-900">{{ t('intake-services__title') }}</h2>
              <p class="mt-1 text-sm text-slate-500">{{ t('intake-services__intro') }}</p>
              <p v-if="errors.services" data-error class="mt-2 text-sm text-red-600">{{ errors.services }}</p>

              <p v-if="catalogError" class="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-700">
                {{ t('intake-services__load-error') }}
                <button type="button" class="font-semibold underline" @click="setMode('callback')">{{ t('intake-services__load-error-link') }}</button>.
              </p>
              <div v-else-if="!catalog" class="mt-4 space-y-3">
                <div v-for="n in 5" :key="n" class="h-16 animate-pulse rounded-xl bg-slate-100" />
              </div>
              <ul v-else class="mt-4 space-y-3">
                <li
                  v-for="service in catalog.services"
                  :key="service.key"
                  class="rounded-xl border transition"
                  :class="selected[service.key] ? 'border-amber-400 bg-amber-50/60 ring-1 ring-amber-400' : 'border-slate-200 hover:border-slate-300'"
                >
                  <label class="flex cursor-pointer items-start gap-3 p-4">
                    <input
                      type="checkbox"
                      class="mt-1 h-5 w-5 rounded border-slate-300 accent-amber-500"
                      :checked="!!selected[service.key]"
                      @change="toggleService(service.key)"
                    />
                    <span class="flex-1">
                      <span class="flex items-baseline justify-between gap-3">
                        <span class="font-medium text-slate-900">
                          {{ service.name }}
                          <span v-if="!service.quote_required" class="font-normal text-slate-500">{{ t('service__hours-estimate', { hours: service.labor_hours }) }}</span>
                        </span>
                        <span class="whitespace-nowrap text-sm font-semibold text-slate-900">
                          <template v-if="service.quote_required">{{ t('landing-pricing__quoted') }}</template>
                          <template v-else>
                            {{ formatMoney(service.price) }}<span v-if="service.unit" class="font-normal text-slate-500">/{{ t(`landing-pricing__unit--${service.unit}`) }}</span>
                          </template>
                        </span>
                      </span>
                      <span class="mt-0.5 block text-sm text-slate-500">{{ service.description }}</span>
                      <span v-if="service.free_addon" class="mt-0.5 block text-xs font-medium text-emerald-700">{{ t('intake-services__hint--free-addon') }}</span>
                    </span>
                  </label>
                  <div
                    v-if="selected[service.key] && service.max_quantity > 1"
                    class="flex flex-wrap items-center gap-2 border-t border-amber-200 px-4 py-3 pl-12"
                  >
                    <span class="text-sm text-slate-600">{{ t('intake-services__axles-label') }}</span>
                    <button
                      v-for="qty in service.max_quantity"
                      :key="qty"
                      type="button"
                      class="rounded-lg px-3 py-1.5 text-sm font-medium"
                      :class="selected[service.key] === qty ? 'bg-slate-900 text-white' : 'bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50'"
                      @click="selected[service.key] = qty"
                    >
                      {{ qty === 1 ? t('intake-services__axles-option--one') : t('intake-services__axles-option--both') }}
                    </button>
                  </div>
                  <div v-if="selected[service.key] && service.quote_required" class="border-t border-amber-200 p-4">
                    <label for="other_description" :class="labelClass">{{ t('intake-services__other-label') }}</label>
                    <textarea
                      id="other_description"
                      v-model="form.other_description"
                      rows="3"
                      maxlength="2000"
                      :placeholder="t('intake-services__other-placeholder')"
                      :class="[inputClass, errors.other_description && 'border-red-400']"
                    />
                    <p v-if="errors.other_description" data-error class="mt-1 text-sm text-red-600">{{ errors.other_description }}</p>
                    <p class="mt-2 text-xs text-slate-500">
                      {{ t('intake-services__other-note') }}
                    </p>
                  </div>
                </li>
              </ul>
            </fieldset>

            <!-- Date -->
            <fieldset v-if="mode === 'booking'" class="intake-date rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
              <legend class="sr-only">{{ t('intake-date__title') }}</legend>
              <h2 class="text-lg font-semibold text-slate-900">{{ t('intake-date__title') }}</h2>
              <p class="mt-1 text-sm text-slate-500">{{ t('intake-date__intro', { days: catalog?.booking_lead_days ?? 14 }) }}</p>
              <input
                id="preferred_date"
                v-model="form.preferred_date"
                type="date"
                :min="minDate"
                :class="[inputClass, 'max-w-xs', errors.preferred_date && 'border-red-400']"
                :aria-label="t('intake-date__title')"
              />
              <p v-if="errors.preferred_date" data-error class="mt-1 text-sm text-red-600">{{ errors.preferred_date }}</p>

              <div v-if="scheduling?.isEmergency" class="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-800 ring-1 ring-red-200">
                <p class="font-semibold">{{ t('intake-date__warning-title--emergency') }}</p>
                <p class="mt-1">
                  {{ t('intake-date__warning-body--emergency', {
                    days: catalog?.emergency_window_days ?? 7,
                    fee: catalog ? formatMoney(catalog.emergency_fee) : ''
                  }) }}
                </p>
              </div>
              <div v-else-if="scheduling?.shortNotice" class="mt-4 rounded-xl bg-amber-50 p-4 text-sm text-amber-900 ring-1 ring-amber-200">
                <p class="font-semibold">{{ t('intake-date__warning-title--short-notice') }}</p>
                <p class="mt-1">{{ t('intake-date__warning-body--short-notice') }}</p>
              </div>
            </fieldset>

            <!-- Contact -->
            <fieldset class="intake-contact rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
              <legend class="sr-only">{{ t('intake-contact__title') }}</legend>
              <h2 class="text-lg font-semibold text-slate-900">{{ t('intake-contact__title') }}</h2>
              <div class="mt-4 grid gap-4 sm:grid-cols-2">
                <div class="sm:col-span-2">
                  <label for="name" :class="labelClass">{{ t('intake-contact__name-label') }}</label>
                  <input id="name" v-model="form.name" type="text" autocomplete="name" maxlength="120" :class="[inputClass, errors.name && 'border-red-400']" />
                  <p v-if="errors.name" data-error class="mt-1 text-sm text-red-600">{{ errors.name }}</p>
                </div>
                <div>
                  <label for="phone" :class="labelClass">{{ t('intake-contact__phone-label') }}</label>
                  <input id="phone" v-model="form.phone" type="tel" autocomplete="tel" maxlength="32" :class="[inputClass, errors.phone && 'border-red-400']" />
                </div>
                <div>
                  <label for="email" :class="labelClass">{{ t('intake-contact__email-label') }}</label>
                  <input id="email" v-model="form.email" type="email" autocomplete="email" :class="[inputClass, errors.email && 'border-red-400']" />
                  <p v-if="errors.email" data-error class="mt-1 text-sm text-red-600">{{ errors.email }}</p>
                </div>
                <p v-if="errors.phone" data-error class="text-sm text-red-600 sm:col-span-2">{{ errors.phone }}</p>
                <div v-if="mode === 'booking'" class="sm:col-span-2">
                  <label for="service_address" :class="labelClass">{{ t('intake-contact__address-label') }} <span class="font-normal text-slate-500">{{ t('intake-contact__address-hint') }}</span></label>
                  <input id="service_address" v-model="form.service_address" type="text" autocomplete="street-address" maxlength="255" :class="inputClass" />
                </div>
                <div class="sm:col-span-2">
                  <label for="notes" :class="labelClass">
                    {{ mode === 'booking' ? t('intake-contact__notes-label--booking') : t('intake-contact__notes-label--callback') }}
                    <span v-if="mode === 'booking'" class="font-normal text-slate-500">{{ t('intake-form__optional') }}</span>
                  </label>
                  <textarea
                    id="notes"
                    v-model="form.notes"
                    :rows="mode === 'booking' ? 3 : 5"
                    maxlength="4000"
                    :placeholder="mode === 'booking' ? t('intake-contact__notes-placeholder--booking') : t('intake-contact__notes-placeholder--callback')"
                    :class="[inputClass, errors.notes && 'border-red-400']"
                  />
                  <p v-if="errors.notes" data-error class="mt-1 text-sm text-red-600">{{ errors.notes }}</p>
                </div>
              </div>
            </fieldset>
          </div>

          <!-- Estimate sidebar -->
          <aside id="estimate" class="intake-estimate relative scroll-mt-20 pb-16 lg:sticky lg:top-24 lg:self-start lg:pb-0">
            <div class="rounded-2xl bg-slate-900 p-6 text-white shadow-lg">
              <template v-if="mode === 'booking'">
                <h2 class="text-lg font-semibold">{{ t('intake-estimate__title') }}</h2>
                <p v-if="selections.length === 0" class="mt-3 text-sm text-slate-400">{{ t('intake-estimate__empty') }}</p>
                <div v-else-if="estimate" class="mt-4 text-sm" :class="estimating && 'opacity-60'">
                  <ul class="space-y-2">
                    <li v-for="item in estimate.line_items" :key="item.key" class="flex justify-between gap-3">
                      <span class="text-slate-300">
                        {{ item.name }}<span v-if="item.quantity > 1"> × {{ item.quantity }}</span>
                      </span>
                      <span>{{ item.quote_required ? t('estimate-breakdown__quote-pending') : formatMoney(item.amount) }}</span>
                    </li>
                    <li v-for="discount in estimate.discounts" :key="discount.key" class="flex justify-between gap-3 text-emerald-400">
                      <span>{{ discount.name }}<span v-if="discount.units > 1"> × {{ discount.units }}</span></span>
                      <span>−{{ formatMoney(discount.amount) }}</span>
                    </li>
                    <li class="flex justify-between gap-3 border-t border-slate-700 pt-2">
                      <span class="text-slate-300">{{ t('intake-estimate__line--service-call') }}</span>
                      <span>{{ formatMoney(estimate.service_call_fee) }}</span>
                    </li>
                    <li v-if="Number(estimate.emergency_fee) > 0" class="flex justify-between gap-3 text-red-300">
                      <span>{{ t('intake-estimate__line--emergency-fee') }}</span>
                      <span>{{ formatMoney(estimate.emergency_fee) }}</span>
                    </li>
                  </ul>
                  <div class="mt-4 flex items-baseline justify-between border-t border-slate-700 pt-4">
                    <span class="font-semibold">{{ t('estimate-breakdown__total') }}</span>
                    <span class="text-2xl font-bold text-amber-400">
                      {{ formatMoney(estimate.total) }}<span v-if="estimate.needs_custom_quote" class="text-base">+</span>
                    </span>
                  </div>
                  <p class="mt-1 text-xs text-slate-400">{{ t('intake-estimate__labor-hours', { hours: estimate.labor_hours }) }}</p>

                  <div v-if="estimate.parts_estimate" class="mt-4 rounded-2xl bg-white p-4 text-left ring-1 ring-slate-200">
                    <PartsEstimateCard
                      :estimate="estimate.parts_estimate"
                      :labor-total="estimate.total"
                      :vehicle-label="[form.vehicle_year, form.vehicle_make, form.vehicle_model].filter(Boolean).join(' ')"
                    />
                  </div>
                </div>
                <p v-else-if="estimating" class="mt-3 text-sm text-slate-400">{{ t('intake-estimate__calculating') }}</p>
                <p v-else class="mt-3 text-sm text-slate-400">{{ t('intake-estimate__error') }}</p>

                <ul class="mt-5 space-y-2 border-t border-slate-700 pt-4 text-xs text-slate-400">
                  <li v-if="!estimate?.parts_estimate">
                    {{ t('parts-policy__short') }}
                    {{ form.vehicle_type ? t('intake-estimate__note--quoted-after-vin') : t('intake-estimate__note--pick-vehicle-type') }}
                  </li>
                  <li>{{ t('intake-estimate__note--preferences') }}</li>
                  <li>{{ t('intake-estimate__note--short-notice') }}</li>
                  <li v-if="selected.other">{{ t('intake-estimate__note--other') }}</li>
                </ul>
              </template>
              <template v-else>
                <h2 class="text-lg font-semibold">{{ t('intake-estimate__callback-title') }}</h2>
                <p class="mt-3 text-sm text-slate-300">{{ t('intake-estimate__callback-body') }}</p>
                <a :href="phoneHref()" class="mt-3 inline-block font-semibold text-amber-400 hover:text-amber-300">
                  {{ business.phone }}
                </a>
              </template>

              <div class="absolute -left-[9999px] h-px w-px overflow-hidden" aria-hidden="true">
                <label for="website">{{ t('intake-form__honeypot-label') }}</label>
                <input id="website" v-model="form.website" type="text" name="website" tabindex="-1" autocomplete="off" />
              </div>
              <TurnstileWidget v-if="captchaRequired" ref="captcha" class="mt-5" @update:token="captchaToken = $event" />

              <p v-if="generalError" class="mt-5 rounded-lg bg-red-500/15 p-3 text-sm text-red-200">{{ generalError }}</p>
              <button
                type="submit"
                :disabled="submitting"
                class="mt-5 w-full rounded-xl bg-amber-400 px-5 py-3 font-semibold text-slate-900 hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {{ submitting ? t('intake-estimate__submit--sending') : mode === 'booking' ? t('intake-estimate__submit--booking') : t('intake-estimate__submit--callback') }}
              </button>
              <p v-if="mode === 'booking'" class="mt-3 text-center text-xs text-slate-400">
                {{ t('intake-estimate__no-payment') }}
              </p>
            </div>
          </aside>

          <!-- Phones: keep the running total visible; the full breakdown sits at the bottom. -->
          <a
            v-if="mode === 'booking' && estimate"
            href="#estimate"
            class="intake-mobile-total fixed inset-x-0 bottom-0 z-20 flex items-center justify-between border-t border-slate-700 bg-slate-900 px-4 py-3 text-white lg:hidden"
          >
            <span class="text-sm text-slate-300">{{ t('estimate-breakdown__total') }}</span>
            <span class="text-lg font-bold text-amber-400">
              {{ formatMoney(estimate.total) }}<span v-if="estimate.needs_custom_quote">+</span>
              <span class="ml-1 text-xs font-medium text-slate-400">{{ t('intake-mobile-total__details-link') }} ↓</span>
            </span>
          </a>
        </form>
      </template>
    </div>
  </div>
</template>
