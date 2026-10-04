<script setup lang="ts">
// One day of dispatch: each yard's stock, each truck's loads and how much of
// its day they use, plus loads nobody's carrying yet. Stock and truck
// switches here feed straight into the next customer's quote.
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StatusBadge from '@/components/StatusBadge.vue'
import { fetchDispatchBoard, setStock, setTruckActive, setTruckDayOff } from '@/services/account'
import type { BoardStock, BoardTruck, DispatchBoard } from '@/types/account'
import { formatDate, isoDateFromToday } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const WINDOW_LABELS: Record<string, string> = { any: '', morning: 'AM', afternoon: 'PM' }

const day = computed(() =>
  typeof route.query.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(route.query.date) ? route.query.date : isoDateFromToday(0)
)

function shift(days: number) {
  const [y, m, d] = day.value.split('-').map(Number)
  const next = new Date(y, m - 1, d + days)
  const iso = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}-${String(next.getDate()).padStart(2, '0')}`
  router.replace({ query: { date: iso } })
}

const board = ref<DispatchBoard | null>(null)
const loading = ref(false)
const loadError = ref(false)
const actionError = ref('')

async function load() {
  loading.value = true
  loadError.value = false
  try {
    board.value = await fetchDispatchBoard(day.value)
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

watch(day, load, { immediate: true })

async function act(action: () => Promise<void>) {
  actionError.value = ''
  try {
    await action()
    await load()
  } catch {
    actionError.value = "That change couldn't be saved. Try again."
  }
}

function toggleStock(stock: BoardStock) {
  if (stock.id !== null) act(() => setStock(stock.id!, !stock.in_stock))
}

const totals = computed(() => {
  const trucks = board.value?.yards.flatMap((y) => y.trucks) ?? []
  const running = trucks.filter((t) => t.active && !t.day_off)
  return {
    loads: trucks.reduce((sum, t) => sum + t.loads.length, 0) + (board.value?.unassigned.length ?? 0),
    yards: trucks.reduce((sum, t) => sum + t.loads.reduce((s, l) => s + l.quantity, 0), 0),
    used: running.reduce((sum, t) => sum + t.used_minutes, 0),
    available: running.reduce((sum, t) => sum + t.workday_minutes, 0)
  }
})

function usage(truck: BoardTruck) {
  return Math.min(100, Math.round((truck.used_minutes / Math.max(truck.workday_minutes, 1)) * 100))
}

function hours(minutes: number) {
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, '0')}`
}
</script>

<template>
  <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
    <router-link to="/dashboard" class="text-sm font-medium text-stone-500 hover:text-stone-800">← Orders</router-link>
    <div class="mt-3 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-stone-900">Dispatch · {{ formatDate(day) }}</h1>
        <p class="mt-1 text-stone-600">
          <template v-if="board && !board.delivery_day">Trucks don't run this day.</template>
          <template v-else>{{ totals.loads }} loads · {{ totals.yards }} yd · {{ hours(totals.used) }} of {{ hours(totals.available) }} truck time booked</template>
        </p>
      </div>
      <div class="flex items-center gap-2">
        <button type="button" class="rounded-lg px-3 py-1.5 text-sm ring-1 ring-stone-300 hover:bg-stone-100" @click="shift(-1)">← Prev</button>
        <button type="button" class="rounded-lg px-3 py-1.5 text-sm ring-1 ring-stone-300 hover:bg-stone-100" @click="router.replace({ query: {} })">Today</button>
        <input
          type="date"
          :value="day"
          class="rounded-lg border border-stone-300 px-2 py-1.5 text-sm"
          aria-label="Day"
          @change="router.replace({ query: { date: ($event.target as HTMLInputElement).value } })"
        />
        <button type="button" class="rounded-lg px-3 py-1.5 text-sm ring-1 ring-stone-300 hover:bg-stone-100" @click="shift(1)">Next →</button>
      </div>
    </div>

    <p v-if="actionError" class="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{{ actionError }}</p>
    <p v-if="loadError" class="mt-6 rounded-xl bg-red-50 p-4 text-sm text-red-700">The board couldn't be loaded. Refresh to try again.</p>
    <div v-else-if="!board" class="mt-6 grid gap-4 lg:grid-cols-3">
      <div v-for="n in 3" :key="n" class="h-64 animate-pulse rounded-2xl bg-stone-200/60" />
    </div>

    <template v-else>
      <!-- Loads with no truck -->
      <section v-if="board.unassigned.length" class="mt-6 rounded-2xl bg-red-50 p-5 ring-1 ring-red-200">
        <h2 class="font-semibold text-red-900">No truck yet ({{ board.unassigned.length }})</h2>
        <ul class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <li v-for="load in board.unassigned" :key="load.id">
            <router-link :to="{ name: 'staff-order', params: { id: load.order_id } }" class="block rounded-xl bg-white p-3 text-sm ring-1 ring-red-200 hover:ring-red-300">
              <p class="font-semibold text-stone-900">#{{ load.order_id }} · {{ load.order_name }}</p>
              <p class="text-stone-600">{{ load.quantity }} yd {{ load.product_name.toLowerCase() }} · {{ load.city || load.zip_code }}</p>
            </router-link>
          </li>
        </ul>
      </section>

      <div class="mt-6 grid gap-6 lg:grid-cols-3" :class="loading && 'opacity-60'">
        <section v-for="yard in board.yards" :key="yard.code" class="flex flex-col rounded-2xl bg-white shadow-sm ring-1 ring-stone-200" :class="!yard.active && 'opacity-60'">
          <header class="rounded-t-2xl bg-stone-900 px-5 py-4 text-white">
            <h2 class="font-semibold">{{ yard.name }}</h2>
            <p class="text-xs text-stone-400">{{ yard.code }}<template v-if="!yard.active"> · inactive (change in the admin)</template></p>
          </header>

          <!-- Stock -->
          <div class="border-b border-stone-100 px-5 py-4">
            <p class="text-xs font-semibold uppercase tracking-wider text-stone-400">Stock · tap to flip</p>
            <div class="mt-2 flex flex-wrap gap-1.5">
              <button
                v-for="stock in yard.stock"
                :key="stock.product"
                type="button"
                :disabled="!stock.carried"
                :title="stock.carried ? stock.note || (stock.in_stock ? 'In stock' : 'Out of stock') : 'Not carried here (add it in the admin)'"
                class="rounded-full px-2.5 py-1 text-xs font-semibold ring-1"
                :class="!stock.carried
                  ? 'cursor-default bg-white text-stone-300 ring-stone-200 line-through'
                  : stock.in_stock
                    ? 'bg-emerald-50 text-emerald-800 ring-emerald-200 hover:bg-emerald-100'
                    : 'bg-red-50 text-red-700 ring-red-200 hover:bg-red-100'"
                @click="toggleStock(stock)"
              >
                {{ stock.product_name }}{{ stock.carried && !stock.in_stock ? ' · out' : '' }}
              </button>
            </div>
          </div>

          <!-- Trucks -->
          <ul class="flex-1 divide-y divide-stone-100">
            <li v-for="truck in yard.trucks" :key="truck.id" class="px-5 py-4">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <p class="font-semibold text-stone-900">{{ truck.name }}</p>
                  <p class="text-xs text-stone-500">{{ truck.capacity_yards }} yd · {{ hours(truck.used_minutes) }} / {{ hours(truck.workday_minutes) }}</p>
                </div>
                <div class="flex flex-col items-end gap-1 text-xs">
                  <label class="flex items-center gap-1.5 text-stone-600">
                    <input type="checkbox" class="accent-lime-600" :checked="truck.active" @change="act(() => setTruckActive(truck.id, !truck.active))" />
                    In service
                  </label>
                  <label class="flex items-center gap-1.5 text-stone-600" :class="!truck.active && 'opacity-50'">
                    <input type="checkbox" class="accent-lime-600" :checked="truck.day_off" :disabled="!truck.active" @change="act(() => setTruckDayOff(truck.id, day, !truck.day_off))" />
                    Off this day
                  </label>
                </div>
              </div>
              <div class="mt-2 h-2 overflow-hidden rounded-full bg-stone-100" role="progressbar" :aria-valuenow="usage(truck)" aria-valuemin="0" aria-valuemax="100" :aria-label="`${truck.name} day booked`">
                <div
                  class="h-full rounded-full"
                  :class="!truck.active || truck.day_off ? 'bg-stone-300' : usage(truck) >= 100 ? 'bg-red-500' : usage(truck) > 80 ? 'bg-amber-500' : 'bg-lime-500'"
                  :style="{ width: `${usage(truck)}%` }"
                />
              </div>
              <p v-if="(truck.day_off || !truck.active) && truck.loads.length" class="mt-2 text-xs font-semibold text-red-700">
                Has loads but isn't running. Move them from each order's page.
              </p>
              <ol v-if="truck.loads.length" class="mt-3 space-y-1.5">
                <li v-for="load in truck.loads" :key="load.id">
                  <router-link :to="{ name: 'staff-order', params: { id: load.order_id } }" class="flex items-center gap-2 rounded-lg bg-stone-50 px-2.5 py-1.5 text-sm hover:bg-stone-100">
                    <span class="min-w-0 flex-1 truncate">
                      <span class="font-medium text-stone-900">#{{ load.order_id }}</span>
                      {{ load.quantity }} yd {{ load.product_name.toLowerCase() }} → {{ load.city || load.zip_code }}
                      <span v-if="WINDOW_LABELS[load.window]" class="text-xs text-stone-500">{{ WINDOW_LABELS[load.window] }}</span>
                    </span>
                    <span class="text-xs text-stone-400">{{ load.minutes }}m</span>
                    <StatusBadge :status="load.order_status" />
                  </router-link>
                </li>
              </ol>
              <p v-else class="mt-2 text-xs text-stone-400">No loads.</p>
            </li>
            <li v-if="!yard.trucks.length" class="px-5 py-4 text-sm text-stone-500">No trucks at this yard.</li>
          </ul>
        </section>
      </div>
      <p v-if="!board.yards.length" class="mt-6 rounded-xl bg-white p-6 text-sm text-stone-600 ring-1 ring-stone-200">
        No yards yet. Add them in the Django admin, or run <code>python manage.py seed_network</code> for the sample ones.
      </p>
    </template>
  </div>
</template>
