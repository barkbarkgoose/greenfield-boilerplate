<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StatusBadge from '@/components/StatusBadge.vue'
import { fetchStaffRequests, fetchStaffSummary } from '@/services/garage'
import type { RequestSummary, StaffSummary } from '@/types/garage'
import { STATUS_OPTIONS, formatDate, formatDateTime, formatMoney, servicesLabel } from '@/utils/intake'

type Row = RequestSummary & { name: string }

const route = useRoute()
const router = useRouter()

const OPEN = 'new,contacted,scheduled'
const tabs = [
  { value: OPEN, label: 'Open' },
  ...STATUS_OPTIONS.map((o) => ({ value: o.value as string, label: o.label })),
  { value: '', label: 'All' }
]

// Filters live in the URL so back/forward and refreshes keep them.
const filters = computed(() => ({
  status: typeof route.query.status === 'string' ? route.query.status : OPEN,
  q: typeof route.query.q === 'string' ? route.query.q : '',
  unread: route.query.unread === '1',
  emergency: route.query.emergency === '1',
  ordering: typeof route.query.ordering === 'string' ? route.query.ordering : 'newest',
  page: Number(route.query.page) || 1
}))

function setFilter(changes: Record<string, string | number | boolean | undefined>) {
  const query: Record<string, string> = {}
  const merged = { ...filters.value, page: 1, ...changes }
  if (merged.status !== OPEN) query.status = String(merged.status)
  if (merged.q) query.q = String(merged.q)
  if (merged.unread) query.unread = '1'
  if (merged.emergency) query.emergency = '1'
  if (merged.ordering !== 'newest') query.ordering = String(merged.ordering)
  if (Number(merged.page) > 1) query.page = String(merged.page)
  router.replace({ query })
}

const summary = ref<StaffSummary | null>(null)
const rows = ref<Row[]>([])
const count = ref(0)
const hasNext = ref(false)
const loading = ref(true)
const loadError = ref(false)

const search = ref(filters.value.q)
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(search, (value) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => setFilter({ q: value.trim() }), 300)
})

async function loadRows() {
  loading.value = true
  loadError.value = false
  try {
    const page = await fetchStaffRequests(filters.value)
    rows.value = page.results
    count.value = page.count
    hasNext.value = !!page.next
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

watch(filters, loadRows, { deep: true })

onMounted(async () => {
  loadRows()
  try {
    summary.value = await fetchStaffSummary()
  } catch {
    // The list still works without the tiles.
  }
})

function when(r: Row): string {
  if (r.scheduled_for) return formatDateTime(r.scheduled_for)
  if (r.preferred_date) return `Wants ${formatDate(r.preferred_date)}`
  return '—'
}
</script>

<template>
  <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
    <div class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-slate-900">Bookings</h1>
        <p class="mt-1 text-slate-600">Requests from the website, newest first.</p>
      </div>
    </div>

    <!-- Summary tiles -->
    <div class="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <button type="button" class="rounded-2xl bg-white p-4 text-left shadow-sm ring-1 ring-slate-200 hover:ring-slate-300" @click="setFilter({ status: 'new', unread: false, emergency: false })">
        <p class="text-sm text-slate-500">New requests</p>
        <p class="mt-1 text-3xl font-bold text-slate-900">{{ summary?.status_counts.new ?? '–' }}</p>
      </button>
      <button type="button" class="rounded-2xl bg-white p-4 text-left shadow-sm ring-1 ring-slate-200 hover:ring-slate-300" @click="setFilter({ status: '', unread: true, emergency: false })">
        <p class="text-sm text-slate-500">Unread messages</p>
        <p class="mt-1 text-3xl font-bold" :class="summary?.unread_messages ? 'text-amber-600' : 'text-slate-900'">{{ summary?.unread_messages ?? '–' }}</p>
      </button>
      <button type="button" class="rounded-2xl bg-white p-4 text-left shadow-sm ring-1 ring-slate-200 hover:ring-slate-300" @click="setFilter({ status: 'new,contacted', unread: false, emergency: true })">
        <p class="text-sm text-slate-500">Open emergencies</p>
        <p class="mt-1 text-3xl font-bold" :class="summary?.emergencies_open ? 'text-red-600' : 'text-slate-900'">{{ summary?.emergencies_open ?? '–' }}</p>
      </button>
      <div class="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p class="text-sm text-slate-500">Received this week</p>
        <p class="mt-1 text-3xl font-bold text-slate-900">{{ summary?.new_this_week ?? '–' }}</p>
      </div>
    </div>

    <!-- Upcoming -->
    <section v-if="summary?.upcoming.length" class="mt-6 rounded-2xl bg-slate-900 p-5 text-white">
      <h2 class="text-sm font-semibold uppercase tracking-wider text-amber-400">Coming up</h2>
      <ul class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <li v-for="r in summary.upcoming" :key="r.id">
          <router-link :to="{ name: 'staff-request', params: { id: r.id } }" class="block rounded-xl bg-slate-800 p-3 hover:bg-slate-700">
            <p class="font-semibold">{{ formatDateTime(r.scheduled_for) }}</p>
            <p class="truncate text-sm text-slate-300">{{ r.vehicle_label || 'Vehicle' }} · {{ servicesLabel(r.services) }}</p>
          </router-link>
        </li>
      </ul>
    </section>

    <!-- Filters -->
    <div class="mt-8 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div class="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1" role="tablist" aria-label="Status">
        <button
          v-for="tab in tabs"
          :key="tab.label"
          type="button"
          role="tab"
          :aria-selected="filters.status === tab.value"
          class="whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium"
          :class="filters.status === tab.value ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-200'"
          @click="setFilter({ status: tab.value })"
        >
          {{ tab.label }}
          <span v-if="summary && tab.value && !tab.value.includes(',')" class="ml-1 text-xs opacity-70">
            {{ summary.status_counts[tab.value as keyof StaffSummary['status_counts']] }}
          </span>
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <input
          v-model="search"
          type="search"
          placeholder="Search name, phone, VIN, car…"
          class="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm sm:w-64 focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-400/40"
          aria-label="Search requests"
        />
        <label class="flex items-center gap-1.5 text-sm text-slate-600">
          <input type="checkbox" class="accent-amber-500" :checked="filters.unread" @change="setFilter({ unread: !filters.unread })" />
          Unread
        </label>
        <label class="flex items-center gap-1.5 text-sm text-slate-600">
          <input type="checkbox" class="accent-amber-500" :checked="filters.emergency" @change="setFilter({ emergency: !filters.emergency })" />
          Emergency
        </label>
        <select
          :value="filters.ordering"
          class="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
          aria-label="Sort"
          @change="setFilter({ ordering: ($event.target as HTMLSelectElement).value })"
        >
          <option value="newest">Newest</option>
          <option value="oldest">Oldest</option>
          <option value="preferred">Preferred date</option>
          <option value="scheduled">Appointment time</option>
        </select>
      </div>
    </div>

    <!-- List -->
    <div class="mt-4 overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
      <p v-if="loadError" class="p-6 text-sm text-red-700">Requests couldn't be loaded. Refresh to try again.</p>
      <p v-else-if="!loading && rows.length === 0" class="p-10 text-center text-sm text-slate-500">Nothing here.</p>
      <ul v-else class="divide-y divide-slate-100" :class="loading && 'opacity-60'">
        <li v-for="r in rows" :key="r.id">
          <router-link
            :to="{ name: 'staff-request', params: { id: r.id } }"
            class="grid gap-x-4 gap-y-1 px-5 py-4 hover:bg-slate-50 md:grid-cols-[4rem_1.2fr_1.5fr_1fr_6rem_6.5rem] md:items-center"
          >
            <span class="text-xs text-slate-400">#{{ r.id }}<span class="block">{{ formatDate(r.created_at).replace(/, \d{4}$/, '') }}</span></span>
            <span class="min-w-0">
              <span class="block truncate font-semibold text-slate-900">{{ r.name }}</span>
              <span class="block truncate text-sm text-slate-500">{{ r.vehicle_label || (r.vin ? r.vin : '') }}</span>
            </span>
            <span class="min-w-0 truncate text-sm text-slate-700">
              <template v-if="r.request_type === 'callback'"><span class="font-medium text-violet-700">Contact me</span></template>
              <template v-else>{{ servicesLabel(r.services) }}</template>
            </span>
            <span class="text-sm text-slate-600">{{ when(r) }}</span>
            <span class="text-sm font-medium text-slate-900">
              {{ r.final_total ? formatMoney(r.final_total) : r.estimated_total ? formatMoney(r.estimated_total) : '' }}
            </span>
            <span class="flex flex-wrap items-center gap-1.5 md:justify-end">
              <span v-if="r.is_emergency" class="rounded-full bg-red-100 px-2 py-0.5 text-xs font-bold text-red-700">Rush</span>
              <span v-if="r.unread_count" class="rounded-full bg-amber-400 px-2 py-0.5 text-xs font-bold text-slate-900" :title="`${r.unread_count} unread`">✉ {{ r.unread_count }}</span>
              <StatusBadge :status="r.status" />
            </span>
          </router-link>
        </li>
      </ul>
      <div v-if="count > rows.length || filters.page > 1" class="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-sm">
        <span class="text-slate-500">{{ count }} total</span>
        <span class="flex gap-2">
          <button type="button" :disabled="filters.page <= 1" class="rounded-lg px-3 py-1.5 ring-1 ring-slate-300 disabled:opacity-40" @click="setFilter({ page: filters.page - 1 })">Previous</button>
          <button type="button" :disabled="!hasNext" class="rounded-lg px-3 py-1.5 ring-1 ring-slate-300 disabled:opacity-40" @click="setFilter({ page: filters.page + 1 })">Next</button>
        </span>
      </div>
    </div>
  </div>
</template>
