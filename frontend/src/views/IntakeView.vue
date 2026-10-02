<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import PublicHeader from '@/components/PublicHeader.vue'
import PublicFooter from '@/components/PublicFooter.vue'
import TurnstileWidget from '@/components/TurnstileWidget.vue'
import { useAuthStore } from '@/stores/auth'
import { fetchMyVehicles } from '@/services/garage'
import type { Vehicle } from '@/types/garage'
import { business } from '@/config/business'
import { decodeVin, fetchCatalog, fetchEstimate, submitServiceRequest } from '@/services/intake'
import { VIN_PATTERN, formatMoney, isoDateFromToday, normalizeVin } from '@/utils/intake'
import type {
  Catalog,
  Estimate,
  RequestType,
  ServiceRequestCreated,
  ServiceSelection
} from '@/types/intake'

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
  [selections, () => form.preferred_date, mode],
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
        const result = await fetchEstimate(selections.value, form.preferred_date || null)
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

function flattenErrors(data: unknown): Record<string, string> {
  if (!data || typeof data !== 'object') return {}
  const result: Record<string, string> = {}
  for (const [field, value] of Object.entries(data as Record<string, unknown>)) {
    if (Array.isArray(value)) {
      const first = value.find((v) => typeof v === 'string')
      result[field] = first ?? 'Please check this field.'
    } else if (typeof value === 'string') {
      result[field] = value
    } else {
      result[field] = 'Please check this field.'
    }
  }
  return result
}

function validateLocally(): Record<string, string> {
  const found: Record<string, string> = {}
  if (!form.name.trim()) found.name = 'Your name, please.'
  if (!form.phone.trim() && !form.email.trim()) found.phone = 'Leave a phone number or email so I can reach you.'
  const vin = normalizeVin(form.vin)
  if (mode.value === 'booking') {
    if (!vin) found.vin = 'A VIN is needed so I can order the right parts.'
    if (selections.value.length === 0) found.services = 'Pick at least one service.'
    if (!form.preferred_date) found.preferred_date = 'Pick a preferred date.'
    if (selected.other && !form.other_description.trim()) {
      found.other_description = 'Tell me a bit about the other work.'
    }
  } else if (!form.notes.trim()) {
    found.notes = 'Leave a short note about what you need.'
  }
  if (vin && !VIN_PATTERN.test(vin)) found.vin = 'A VIN is 17 letters and numbers (never I, O or Q).'
  if (captchaRequired.value && !captchaToken.value) found.captcha_token = 'Please complete the verification.'
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
      services: isBooking ? selections.value : [],
      other_description: isBooking && selected.other ? form.other_description.trim() : '',
      preferred_date: isBooking ? form.preferred_date : null,
      notes: form.notes.trim(),
      website: form.website,
      captcha_token: captchaToken.value
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 400) {
      errors.value = flattenErrors(error.response.data)
      generalError.value =
        errors.value.captcha_token || errors.value.detail || 'Please fix the highlighted fields.'
      // Turnstile tokens are single-use; get a fresh one for the retry.
      captcha.value?.reset()
    } else if (axios.isAxiosError(error) && error.response?.status === 429) {
      generalError.value = `Too many requests from this connection. Please call or text ${business.phone}.`
    } else {
      generalError.value = `Something went wrong sending your request. Please try again or call ${business.phone}.`
    }
  } finally {
    submitting.value = false
  }
}

function startOver() {
  submitted.value = null
  for (const key of Object.keys(selected)) delete selected[key]
  Object.assign(form, {
    vin: '',
    vehicle_year: '',
    vehicle_make: '',
    vehicle_model: '',
    other_description: '',
    preferred_date: isoDateFromToday(14),
    notes: ''
  })
  lastDecodedVin = ''
  vinStatus.value = 'idle'
  captchaToken.value = ''
}

onMounted(async () => {
  if (typeof route.query.vin === 'string') form.vin = route.query.vin

  if (authStore.isAuthenticated && !authStore.isStaff) {
    form.name = authStore.user?.name ?? ''
    form.email = authStore.user?.email ?? ''
    fetchMyVehicles()
      .then((vehicles) => {
        garage.value = vehicles
        const match = vehicles.find((v) => v.vin === normalizeVin(form.vin))
        if (match) useVehicle(match)
      })
      .catch(() => {})
  }

  try {
    catalog.value = await fetchCatalog()
  } catch {
    catalogError.value = true
  }
})

const inputClass =
  'mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-400/40'
const labelClass = 'block text-sm font-medium text-slate-700'
</script>

<template>
  <div class="flex min-h-screen flex-col bg-slate-50">
    <PublicHeader />

    <div class="mx-auto w-full max-w-6xl flex-1 px-4 py-10 sm:px-6">
      <!-- Confirmation -->
      <section v-if="submitted" class="mx-auto max-w-2xl rounded-3xl bg-white p-8 text-center shadow-sm ring-1 ring-slate-200">
        <div class="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
          <svg class="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 class="mt-5 text-2xl font-bold text-slate-900">
          {{ submitted.request_type === 'booking' ? 'Request received!' : 'Got your note!' }}
        </h1>
        <p class="mt-3 text-slate-600">
          <template v-if="submitted.request_type === 'booking'">
            I'll look up parts for your vehicle and reach out to confirm a time
            <template v-if="submitted.preferred_date">around {{ submitted.preferred_date }}</template>
            along with a parts quote.
          </template>
          <template v-else>I'll get back to you as soon as I can.</template>
        </p>
        <p
          v-if="submitted.request_type === 'booking' && 'total' in submitted.estimate"
          class="mt-6 rounded-2xl bg-slate-50 p-4 text-slate-700"
        >
          Estimated labor &amp; fees:
          <span class="text-xl font-bold text-slate-900">{{ formatMoney(submitted.estimate.total) }}</span>
          <span class="block text-xs text-slate-500">Plus parts. Final price confirmed before any work starts.</span>
        </p>
        <div v-if="submitted.claim_token" class="mt-6 rounded-2xl bg-amber-50 p-5 text-left ring-1 ring-amber-200">
          <p class="font-semibold text-slate-900">Save this to your garage</p>
          <p class="mt-1 text-sm text-slate-700">
            Create a free account to track this request, message me with questions, and keep a repair
            history for your car. The link is also in your confirmation email.
          </p>
          <div class="mt-4 flex flex-col gap-2 sm:flex-row">
            <router-link
              :to="{ name: 'register', query: { redirect: `/claim/${submitted.claim_token}` } }"
              class="rounded-xl bg-slate-900 px-4 py-2 text-center text-sm font-semibold text-white hover:bg-slate-800"
            >
              Create account
            </router-link>
            <router-link
              :to="{ name: 'login', query: { redirect: `/claim/${submitted.claim_token}` } }"
              class="rounded-xl px-4 py-2 text-center text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-white"
            >
              I already have one
            </router-link>
          </div>
        </div>
        <router-link
          v-else-if="authStore.isAuthenticated"
          :to="{ name: 'account-request', params: { id: submitted.id } }"
          class="mt-6 inline-block font-semibold text-amber-700 hover:text-amber-600"
        >
          Track it in your garage →
        </router-link>
        <p class="mt-6 text-sm text-slate-500">Reference #{{ submitted.id }} · Questions? {{ business.phone }}</p>
        <div class="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
          <router-link to="/" class="rounded-xl border border-slate-300 px-5 py-2.5 font-semibold text-slate-700 hover:bg-slate-50">
            Back to home
          </router-link>
          <button type="button" class="rounded-xl bg-slate-900 px-5 py-2.5 font-semibold text-white hover:bg-slate-800" @click="startOver">
            Submit another request
          </button>
        </div>
      </section>

      <template v-else>
        <div class="max-w-2xl">
          <h1 class="text-3xl font-bold tracking-tight text-slate-900">
            {{ mode === 'booking' ? 'Book service' : 'Have me contact you' }}
          </h1>
          <p class="mt-2 text-slate-600">
            <template v-if="mode === 'booking'">
              Tell me about your vehicle and the work you need. Your estimate updates as you go.
            </template>
            <template v-else>
              Not sure what you need? Leave a note and I'll call, text or email you back.
            </template>
          </p>
        </div>

        <div class="mt-6 inline-flex rounded-xl bg-slate-200 p-1" role="tablist" aria-label="Request type">
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'booking'"
            class="rounded-lg px-4 py-2 text-sm font-semibold transition"
            :class="mode === 'booking' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'"
            @click="setMode('booking')"
          >
            Book service
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'callback'"
            class="rounded-lg px-4 py-2 text-sm font-semibold transition"
            :class="mode === 'callback' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'"
            @click="setMode('callback')"
          >
            Just contact me
          </button>
        </div>

        <form class="mt-8 grid gap-8 lg:grid-cols-[1fr_22rem]" novalidate @submit.prevent="handleSubmit">
          <div class="space-y-8">
            <!-- Vehicle -->
            <fieldset class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
              <legend class="sr-only">Vehicle</legend>
              <h2 class="text-lg font-semibold text-slate-900">
                Your vehicle
                <span v-if="mode === 'callback'" class="text-sm font-normal text-slate-500">(optional)</span>
              </h2>
              <div v-if="garage.length" class="mt-3 flex flex-wrap gap-2">
                <span class="w-full text-sm text-slate-500">From your garage:</span>
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
                <label for="vin" :class="labelClass">VIN (Vehicle Identification Number)</label>
                <input
                  id="vin"
                  v-model="form.vin"
                  type="text"
                  inputmode="text"
                  autocomplete="off"
                  autocapitalize="characters"
                  spellcheck="false"
                  maxlength="20"
                  placeholder="17 characters, e.g. 1HGCM82633A004352"
                  :class="[inputClass, 'font-mono uppercase tracking-wider', errors.vin && 'border-red-400']"
                  :aria-invalid="!!errors.vin"
                />
                <p v-if="errors.vin" data-error class="mt-1 text-sm text-red-600">{{ errors.vin }}</p>
                <p v-else-if="vinStatus === 'decoding'" class="mt-1 text-sm text-slate-500">Looking up your vehicle…</p>
                <p v-else-if="vinStatus === 'decoded'" class="mt-1 text-sm text-emerald-700">
                  Found it: {{ form.vehicle_year }} {{ form.vehicle_make }} {{ form.vehicle_model }}
                </p>
                <p v-else-if="vinStatus === 'unknown'" class="mt-1 text-sm text-slate-500">
                  Couldn't look that VIN up automatically. Double-check it, or fill in the details below.
                </p>
                <p v-else-if="form.vin && !vinValid" class="mt-1 text-sm text-slate-500">
                  {{ normalizeVin(form.vin).length }}/17 characters
                </p>
                <p v-else class="mt-1 text-xs text-slate-500">
                  Find it on the driver-side dashboard (through the windshield), the door jamb sticker, or your registration/insurance card.
                </p>
              </div>
              <div class="mt-4 grid grid-cols-[6rem_1fr_1fr] gap-3">
                <div>
                  <label for="vehicle_year" :class="labelClass">Year</label>
                  <input id="vehicle_year" v-model="form.vehicle_year" type="text" inputmode="numeric" maxlength="4" :class="inputClass" />
                </div>
                <div>
                  <label for="vehicle_make" :class="labelClass">Make</label>
                  <input id="vehicle_make" v-model="form.vehicle_make" type="text" maxlength="60" :class="inputClass" />
                </div>
                <div>
                  <label for="vehicle_model" :class="labelClass">Model</label>
                  <input id="vehicle_model" v-model="form.vehicle_model" type="text" maxlength="60" :class="inputClass" />
                </div>
              </div>
            </fieldset>

            <!-- Services -->
            <fieldset v-if="mode === 'booking'" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
              <legend class="sr-only">Services</legend>
              <h2 class="text-lg font-semibold text-slate-900">Work needed</h2>
              <p class="mt-1 text-sm text-slate-500">Labor prices shown. Brake and suspension work on the same axle is bundled for less.</p>
              <p v-if="errors.services" data-error class="mt-2 text-sm text-red-600">{{ errors.services }}</p>

              <p v-if="catalogError" class="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-700">
                The service list couldn't be loaded.
                <button type="button" class="font-semibold underline" @click="setMode('callback')">Send me a note instead</button>.
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
                        <span class="font-medium text-slate-900">{{ service.name }}</span>
                        <span class="whitespace-nowrap text-sm font-semibold text-slate-900">
                          <template v-if="service.quote_required">Quoted</template>
                          <template v-else>
                            {{ formatMoney(service.price) }}<span v-if="service.unit" class="font-normal text-slate-500">/{{ service.unit }}</span>
                          </template>
                        </span>
                      </span>
                      <span class="mt-0.5 block text-sm text-slate-500">{{ service.description }}</span>
                    </span>
                  </label>
                  <div
                    v-if="selected[service.key] && service.max_quantity > 1"
                    class="flex flex-wrap items-center gap-2 border-t border-amber-200 px-4 py-3 pl-12"
                  >
                    <span class="text-sm text-slate-600">How many axles?</span>
                    <button
                      v-for="qty in service.max_quantity"
                      :key="qty"
                      type="button"
                      class="rounded-lg px-3 py-1.5 text-sm font-medium"
                      :class="selected[service.key] === qty ? 'bg-slate-900 text-white' : 'bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50'"
                      @click="selected[service.key] = qty"
                    >
                      {{ qty === 1 ? 'One (front or rear)' : 'Both' }}
                    </button>
                  </div>
                  <div v-if="selected[service.key] && service.quote_required" class="border-t border-amber-200 p-4">
                    <label for="other_description" :class="labelClass">Describe the work or the problem</label>
                    <textarea
                      id="other_description"
                      v-model="form.other_description"
                      rows="3"
                      maxlength="2000"
                      placeholder="e.g. check engine light, squeal when turning, replace a window regulator…"
                      :class="[inputClass, errors.other_description && 'border-red-400']"
                    />
                    <p v-if="errors.other_description" data-error class="mt-1 text-sm text-red-600">{{ errors.other_description }}</p>
                    <p class="mt-2 text-xs text-slate-500">
                      Some jobs need a lift or shop equipment and may not be something I can do on-site. I'll let you know either way.
                    </p>
                  </div>
                </li>
              </ul>
            </fieldset>

            <!-- Date -->
            <fieldset v-if="mode === 'booking'" class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
              <legend class="sr-only">Preferred date</legend>
              <h2 class="text-lg font-semibold text-slate-900">Preferred date</h2>
              <p class="mt-1 text-sm text-slate-500">
                Appointments are usually booked about {{ catalog?.booking_lead_days ?? 14 }} days out so I can order parts. I'll confirm the exact time with you.
              </p>
              <input
                id="preferred_date"
                v-model="form.preferred_date"
                type="date"
                :min="minDate"
                :class="[inputClass, 'max-w-xs', errors.preferred_date && 'border-red-400']"
                aria-label="Preferred date"
              />
              <p v-if="errors.preferred_date" data-error class="mt-1 text-sm text-red-600">{{ errors.preferred_date }}</p>

              <div v-if="scheduling?.isEmergency" class="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-800 ring-1 ring-red-200">
                <p class="font-semibold">Same-week emergency job</p>
                <p class="mt-1">
                  Jobs within {{ catalog?.emergency_window_days }} days add a
                  {{ catalog ? formatMoney(catalog.emergency_fee) : '' }} emergency fee and depend on availability.
                  Parts will likely have to be bought locally, which is usually more expensive.
                </p>
              </div>
              <div v-else-if="scheduling?.shortNotice" class="mt-4 rounded-xl bg-amber-50 p-4 text-sm text-amber-900 ring-1 ring-amber-200">
                <p class="font-semibold">Short notice</p>
                <p class="mt-1">
                  There may not be time to order parts ahead, so they may have to come from a local store at a higher price.
                </p>
              </div>
            </fieldset>

            <!-- Contact -->
            <fieldset class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
              <legend class="sr-only">Contact details</legend>
              <h2 class="text-lg font-semibold text-slate-900">How do I reach you?</h2>
              <div class="mt-4 grid gap-4 sm:grid-cols-2">
                <div class="sm:col-span-2">
                  <label for="name" :class="labelClass">Name</label>
                  <input id="name" v-model="form.name" type="text" autocomplete="name" maxlength="120" :class="[inputClass, errors.name && 'border-red-400']" />
                  <p v-if="errors.name" data-error class="mt-1 text-sm text-red-600">{{ errors.name }}</p>
                </div>
                <div>
                  <label for="phone" :class="labelClass">Phone</label>
                  <input id="phone" v-model="form.phone" type="tel" autocomplete="tel" maxlength="32" :class="[inputClass, errors.phone && 'border-red-400']" />
                </div>
                <div>
                  <label for="email" :class="labelClass">Email</label>
                  <input id="email" v-model="form.email" type="email" autocomplete="email" :class="[inputClass, errors.email && 'border-red-400']" />
                  <p v-if="errors.email" data-error class="mt-1 text-sm text-red-600">{{ errors.email }}</p>
                </div>
                <p v-if="errors.phone" data-error class="text-sm text-red-600 sm:col-span-2">{{ errors.phone }}</p>
                <div v-if="mode === 'booking'" class="sm:col-span-2">
                  <label for="service_address" :class="labelClass">Where is the vehicle? <span class="font-normal text-slate-500">(address or ZIP)</span></label>
                  <input id="service_address" v-model="form.service_address" type="text" autocomplete="street-address" maxlength="255" :class="inputClass" />
                </div>
                <div class="sm:col-span-2">
                  <label for="notes" :class="labelClass">
                    {{ mode === 'booking' ? 'Anything else I should know?' : 'What can I help with?' }}
                    <span v-if="mode === 'booking'" class="font-normal text-slate-500">(optional)</span>
                  </label>
                  <textarea
                    id="notes"
                    v-model="form.notes"
                    :rows="mode === 'booking' ? 3 : 5"
                    maxlength="4000"
                    :placeholder="mode === 'booking' ? 'Front or rear axle, symptoms, parking/access notes, best time to call…' : 'Describe what\'s going on with the car and the best way and time to reach you.'"
                    :class="[inputClass, errors.notes && 'border-red-400']"
                  />
                  <p v-if="errors.notes" data-error class="mt-1 text-sm text-red-600">{{ errors.notes }}</p>
                </div>
              </div>
            </fieldset>
          </div>

          <!-- Estimate sidebar -->
          <aside id="estimate" class="relative scroll-mt-20 pb-16 lg:sticky lg:top-24 lg:self-start lg:pb-0">
            <div class="rounded-2xl bg-slate-900 p-6 text-white shadow-lg">
              <template v-if="mode === 'booking'">
                <h2 class="text-lg font-semibold">Your estimate</h2>
                <p v-if="selections.length === 0" class="mt-3 text-sm text-slate-400">
                  Pick a service to see your price.
                </p>
                <div v-else-if="estimate" class="mt-4 text-sm" :class="estimating && 'opacity-60'">
                  <ul class="space-y-2">
                    <li v-for="item in estimate.line_items" :key="item.key" class="flex justify-between gap-3">
                      <span class="text-slate-300">
                        {{ item.name }}<span v-if="item.quantity > 1"> × {{ item.quantity }}</span>
                      </span>
                      <span>{{ item.quote_required ? 'TBD' : formatMoney(item.amount) }}</span>
                    </li>
                    <li v-for="discount in estimate.discounts" :key="discount.key" class="flex justify-between gap-3 text-emerald-400">
                      <span>{{ discount.name }}<span v-if="discount.units > 1"> × {{ discount.units }}</span></span>
                      <span>−{{ formatMoney(discount.amount) }}</span>
                    </li>
                    <li class="flex justify-between gap-3 border-t border-slate-700 pt-2">
                      <span class="text-slate-300">Service call (travel)</span>
                      <span>{{ formatMoney(estimate.service_call_fee) }}</span>
                    </li>
                    <li v-if="Number(estimate.emergency_fee) > 0" class="flex justify-between gap-3 text-red-300">
                      <span>Same-week emergency fee</span>
                      <span>{{ formatMoney(estimate.emergency_fee) }}</span>
                    </li>
                  </ul>
                  <div class="mt-4 flex items-baseline justify-between border-t border-slate-700 pt-4">
                    <span class="font-semibold">Estimated total</span>
                    <span class="text-2xl font-bold text-amber-400">
                      {{ formatMoney(estimate.total) }}<span v-if="estimate.needs_custom_quote" class="text-base">+</span>
                    </span>
                  </div>
                  <p class="mt-1 text-xs text-slate-400">About {{ estimate.labor_hours }} hr of labor. Parts not included.</p>
                </div>
                <p v-else-if="estimating" class="mt-3 text-sm text-slate-400">Calculating…</p>
                <p v-else class="mt-3 text-sm text-slate-400">The estimate couldn't be calculated right now. You can still submit.</p>

                <ul class="mt-5 space-y-2 border-t border-slate-700 pt-4 text-xs text-slate-400">
                  <li>Parts are quoted separately after I look up your VIN.</li>
                  <li>Parts bought locally on short notice are likely to cost more than ordered parts.</li>
                  <li v-if="selected.other">"Other" work is quoted after I review it and may not be something I can cover.</li>
                </ul>
              </template>
              <template v-else>
                <h2 class="text-lg font-semibold">I'll reach out</h2>
                <p class="mt-3 text-sm text-slate-300">
                  Leave a note and I'll get back to you, usually within a business day. Prefer to talk now?
                </p>
                <a :href="`tel:${business.phone.replace(/[^\d+]/g, '')}`" class="mt-3 inline-block font-semibold text-amber-400 hover:text-amber-300">
                  {{ business.phone }}
                </a>
              </template>

              <div class="absolute -left-[9999px] h-px w-px overflow-hidden" aria-hidden="true">
                <label for="website">Leave this empty</label>
                <input id="website" v-model="form.website" type="text" name="website" tabindex="-1" autocomplete="off" />
              </div>
              <TurnstileWidget v-if="captchaRequired" ref="captcha" class="mt-5" @update:token="captchaToken = $event" />

              <p v-if="generalError" class="mt-5 rounded-lg bg-red-500/15 p-3 text-sm text-red-200">{{ generalError }}</p>
              <button
                type="submit"
                :disabled="submitting"
                class="mt-5 w-full rounded-xl bg-amber-400 px-5 py-3 font-semibold text-slate-900 hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {{ submitting ? 'Sending…' : mode === 'booking' ? 'Request appointment' : 'Send note' }}
              </button>
              <p v-if="mode === 'booking'" class="mt-3 text-center text-xs text-slate-400">
                No payment now. I'll confirm the final price before any work starts.
              </p>
            </div>
          </aside>

          <!-- Phones: keep the running total visible; the full breakdown sits at the bottom. -->
          <a
            v-if="mode === 'booking' && estimate"
            href="#estimate"
            class="fixed inset-x-0 bottom-0 z-20 flex items-center justify-between border-t border-slate-700 bg-slate-900 px-4 py-3 text-white lg:hidden"
          >
            <span class="text-sm text-slate-300">Estimated total</span>
            <span class="text-lg font-bold text-amber-400">
              {{ formatMoney(estimate.total) }}<span v-if="estimate.needs_custom_quote">+</span>
              <span class="ml-1 text-xs font-medium text-slate-400">See details ↓</span>
            </span>
          </a>
        </form>
      </template>
    </div>

    <PublicFooter />
  </div>
</template>
