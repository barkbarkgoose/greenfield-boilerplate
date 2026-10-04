<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StatusBadge from '@/components/StatusBadge.vue'
import { fetchStaffOrders, fetchStaffSummary } from '@/services/account'
import type { StaffOrderSummary, StaffSummary } from '@/types/account'
import { STATUS_OPTIONS, formatDate, formatMoney, itemsLabel } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const OPEN = 'new,contacted,scheduled'
const tabs = [
  { value: OPEN, label: 'Open' },
  ...STATUS_OPTIONS.map((o) => ({ value: o.value as string, label: o.label })),
  { value: '', label: 'All' }
]
const WINDOW_LABELS: Record<string, string> = { any: '', morning: 'AM', afternoon: 'PM' }

// Filters live in the URL so back/forward and refreshes keep them.
const filters = computed(() => ({
  status: typeof route.query.status === 'string' ? route.query.status : OPEN,
  q: typeof route.query.q === 'string' ? route.query.q : '',
  unread: route.query.unread === '1',
  rush: route.query.rush === '1',
  needsDispatch: route.query.needs_dispatch === '1',
  ordering: typeof route.query.ordering === 'string' ? route.query.ordering : 'newest',
  page: Number(route.query.page) || 1
}))

function setFilter(changes: Record<string, string | number | boolean | undefined>) {
  const query: Record<string, string> = {}
  const merged = { ...filters.value, page: 1, ...changes }
  if (merged.status !== OPEN) query.status = String(merged.status)
  if (merged.q) query.q = String(merged.q)
  if (merged.unread) query.unread = '1'
  if (merged.rush) query.rush = '1'
  if (merged.needsDispatch) query.needs_dispatch = '1'
  if (merged.ordering !== 'newest') query.ordering = String(merged.ordering)
  if (Number(merged.page) > 1) query.page = String(merged.page)
  router.replace({ query })
}

const summary = ref<StaffSummary | null>(null)
const rows = ref<StaffOrderSummary[]>([])
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
    const page = await fetchStaffOrders(filters.value)
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

function when(r: StaffOrderSummary): string {
  const window = WINDOW_LABELS[r.delivery_window] ? ` ${WINDOW_LABELS[r.delivery_window]}` : ''
  if (r.delivered_on) return `Delivered ${formatDate(r.delivered_on)}`
  if (r.scheduled_date) return `${formatDate(r.scheduled_date)}${window}`
  if (r.preferred_date) return `Wants ${formatDate(r.preferred_date)}${window}`
  return '—'
}

const tileClass = 'rounded-2xl bg-white p-4 text-left shadow-sm ring-1 ring-stone-200 hover:ring-stone-300'
</script>

<template>
  <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-stone-900">Orders</h1>
        <p class="mt-1 text-stone-600">Orders and special requests from the website, newest first.</p>
      </div>
      <router-link :to="{ name: 'dispatch' }" class="rounded-xl bg-stone-900 px-4 py-2 text-center font-semibold text-white hover:bg-stone-800">
        Dispatch board →
      </router-link>
    </div>

    <!-- Summary tiles -->
    <div class="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
      <button type="button" :class="tileClass" @click="setFilter({ status: 'new', unread: false, rush: false, needsDispatch: false })">
        <p class="text-sm text-stone-500">New orders</p>
        <p class="mt-1 text-3xl font-bold text-stone-900">{{ summary?.status_counts.new ?? '–' }}</p>
      </button>
      <button type="button" :class="tileClass" @click="setFilter({ status: OPEN, unread: false, rush: false, needsDispatch: true })">
        <p class="text-sm text-stone-500">Need a truck / stock</p>
        <p class="mt-1 text-3xl font-bold" :class="summary?.needs_dispatch ? 'text-red-600' : 'text-stone-900'">{{ summary?.needs_dispatch ?? '–' }}</p>
      </button>
      <button type="button" :class="tileClass" @click="setFilter({ status: 'new,contacted', unread: false, rush: true, needsDispatch: false })">
        <p class="text-sm text-stone-500">Unscheduled rush</p>
        <p class="mt-1 text-3xl font-bold" :class="summary?.rush_open ? 'text-orange-600' : 'text-stone-900'">{{ summary?.rush_open ?? '–' }}</p>
      </button>
      <button v-if="summary?.messaging_enabled" type="button" :class="tileClass" @click="setFilter({ status: '', unread: true, rush: false, needsDispatch: false })">
        <p class="text-sm text-stone-500">Unread messages</p>
        <p class="mt-1 text-3xl font-bold" :class="summary?.unread_messages ? 'text-lime-700' : 'text-stone-900'">{{ summary?.unread_messages ?? '–' }}</p>
      </button>
      <router-link v-else :to="{ name: 'dispatch' }" :class="tileClass">
        <p class="text-sm text-stone-500">Loads today</p>
        <p class="mt-1 text-3xl font-bold text-stone-900">{{ summary?.loads_today ?? '–' }}</p>
      </router-link>
      <div class="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-stone-200">
        <p class="text-sm text-stone-500">Received this week</p>
        <p class="mt-1 text-3xl font-bold text-stone-900">{{ summary?.new_this_week ?? '–' }}</p>
      </div>
    </div>

    <!-- Upcoming -->
    <section v-if="summary?.upcoming.length" class="mt-6 rounded-2xl bg-stone-900 p-5 text-white">
      <h2 class="text-sm font-semibold uppercase tracking-wider text-lime-400">Scheduled deliveries</h2>
      <ul class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <li v-for="r in summary.upcoming" :key="r.id">
          <router-link :to="{ name: 'staff-order', params: { id: r.id } }" class="block rounded-xl bg-stone-800 p-3 hover:bg-stone-700">
            <p class="font-semibold">{{ when(r) }} · {{ r.name }}</p>
            <p class="truncate text-sm text-stone-300">{{ r.city || r.zip_code }} · {{ itemsLabel(r.items) }}</p>
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
          :class="filters.status === tab.value ? 'bg-stone-900 text-white' : 'text-stone-600 hover:bg-stone-200'"
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
          placeholder="Search name, phone, ZIP, address…"
          class="w-full rounded-lg border border-stone-300 px-3 py-1.5 text-sm focus:border-lime-600 focus:outline-none focus:ring-2 focus:ring-lime-500/40 sm:w-64"
          aria-label="Search orders"
        />
        <label v-if="summary?.messaging_enabled" class="flex items-center gap-1.5 text-sm text-stone-600">
          <input type="checkbox" class="accent-lime-600" :checked="filters.unread" @change="setFilter({ unread: !filters.unread })" />
          Unread
        </label>
        <label class="flex items-center gap-1.5 text-sm text-stone-600">
          <input type="checkbox" class="accent-lime-600" :checked="filters.rush" @change="setFilter({ rush: !filters.rush })" />
          Rush
        </label>
        <label class="flex items-center gap-1.5 text-sm text-stone-600">
          <input type="checkbox" class="accent-lime-600" :checked="filters.needsDispatch" @change="setFilter({ needsDispatch: !filters.needsDispatch })" />
          Needs dispatch
        </label>
        <select
          :value="filters.ordering"
          class="rounded-lg border border-stone-300 px-2 py-1.5 text-sm"
          aria-label="Sort"
          @change="setFilter({ ordering: ($event.target as HTMLSelectElement).value })"
        >
          <option value="newest">Newest</option>
          <option value="oldest">Oldest</option>
          <option value="preferred">Wanted date</option>
          <option value="scheduled">Delivery date</option>
        </select>
      </div>
    </div>

    <!-- List -->
    <div class="mt-4 overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-stone-200">
      <p v-if="loadError" class="p-6 text-sm text-red-700">Orders couldn't be loaded. Refresh to try again.</p>
      <p v-else-if="!loading && rows.length === 0" class="p-10 text-center text-sm text-stone-500">Nothing here.</p>
      <ul v-else class="divide-y divide-stone-100" :class="loading && 'opacity-60'">
        <li v-for="r in rows" :key="r.id">
          <router-link
            :to="{ name: 'staff-order', params: { id: r.id } }"
            class="grid gap-x-4 gap-y-1 px-5 py-4 hover:bg-stone-50 md:grid-cols-[4rem_1.2fr_1.5fr_1fr_6rem_8rem] md:items-center"
          >
            <span class="text-xs text-stone-400">#{{ r.id }}<span class="block">{{ formatDate(r.created_at).replace(/, \d{4}$/, '') }}</span></span>
            <span class="min-w-0">
              <span class="block truncate font-semibold text-stone-900">{{ r.name }}</span>
              <span class="block truncate text-sm text-stone-500">{{ [r.city, r.zip_code].filter(Boolean).join(' ') }}</span>
            </span>
            <span class="min-w-0 truncate text-sm text-stone-700">
              <span v-if="r.request_type === 'callback'" class="font-medium text-violet-700">Special request<template v-if="r.items.length">: </template></span>
              {{ itemsLabel(r.items) }}
            </span>
            <span class="text-sm text-stone-600">{{ when(r) }}</span>
            <span class="text-sm font-medium text-stone-900">
              {{ r.final_total ? formatMoney(r.final_total) : r.estimated_total ? formatMoney(r.estimated_total) : '' }}
            </span>
            <span class="flex flex-wrap items-center gap-1.5 md:justify-end">
              <span v-if="r.is_rush" class="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-bold text-orange-700">Rush</span>
              <span v-if="r.plan_status === 'no_capacity'" class="rounded-full bg-red-100 px-2 py-0.5 text-xs font-bold text-red-700">No truck</span>
              <span v-if="r.plan_status === 'out_of_stock'" class="rounded-full bg-red-100 px-2 py-0.5 text-xs font-bold text-red-700">Out of stock</span>
              <span v-if="r.unread_count" class="rounded-full bg-lime-500 px-2 py-0.5 text-xs font-bold text-stone-900" :title="`${r.unread_count} unread`">✉ {{ r.unread_count }}</span>
              <StatusBadge :status="r.status" />
            </span>
          </router-link>
        </li>
      </ul>
      <div v-if="count > rows.length || filters.page > 1" class="flex items-center justify-between border-t border-stone-100 px-5 py-3 text-sm">
        <span class="text-stone-500">{{ count }} total</span>
        <span class="flex gap-2">
          <button type="button" :disabled="filters.page <= 1" class="rounded-lg px-3 py-1.5 ring-1 ring-stone-300 disabled:opacity-40" @click="setFilter({ page: filters.page - 1 })">Previous</button>
          <button type="button" :disabled="!hasNext" class="rounded-lg px-3 py-1.5 ring-1 ring-stone-300 disabled:opacity-40" @click="setFilter({ page: filters.page + 1 })">Next</button>
        </span>
      </div>
    </div>
  </div>
</template>
