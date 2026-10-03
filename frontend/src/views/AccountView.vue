<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import StatusBadge from '@/components/StatusBadge.vue'
import { useAuthStore } from '@/stores/auth'
import { fetchMyRequests, fetchMyVehicles, renameVehicle } from '@/services/garage'
import type { RequestSummary, Vehicle } from '@/types/garage'
import { formatDate, formatMoney, servicesLabel } from '@/utils/intake'
import { intlLocale } from '@/i18n'

const { t } = useI18n()
const authStore = useAuthStore()

const vehicles = ref<Vehicle[]>([])
const requests = ref<RequestSummary[]>([])
const loading = ref(true)
const loadError = ref(false)

const firstName = computed(() => authStore.user?.name?.split(' ')[0] || '')
const looseRequests = computed(() => requests.value.filter((r) => !r.vehicle_id))
const unreadByRequest = computed(() => new Map(requests.value.map((r) => [r.id, r.unread_count])))
const totalUnread = computed(() => requests.value.reduce((sum, r) => sum + r.unread_count, 0))

function serviceDate(r: RequestSummary): string {
  return r.completed_on || r.scheduled_for?.slice(0, 10) || r.preferred_date || r.created_at.slice(0, 10)
}

function lastCompleted(vehicle: Vehicle) {
  return vehicle.history.find((r) => r.status === 'completed')
}

function lastOdometer(vehicle: Vehicle) {
  return vehicle.history.find((r) => r.odometer)?.odometer ?? null
}

// --- Nicknames ---
const editingId = ref<number | null>(null)
const nicknameDraft = ref('')

function startRename(vehicle: Vehicle) {
  editingId.value = vehicle.id
  nicknameDraft.value = vehicle.nickname
}

async function saveRename(vehicle: Vehicle) {
  try {
    const updated = await renameVehicle(vehicle.id, nicknameDraft.value.trim())
    Object.assign(vehicle, { nickname: updated.nickname, label: updated.label })
  } finally {
    editingId.value = null
  }
}

onMounted(async () => {
  try {
    ;[vehicles.value, requests.value] = await Promise.all([fetchMyVehicles(), fetchMyRequests()])
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="mx-auto max-w-5xl px-4 py-8 sm:px-6">
    <div class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-slate-900">
          {{ firstName ? t('garage-overview__title', { name: firstName }) : t('garage-overview__title--anonymous') }}
        </h1>
        <p class="mt-1 text-slate-600">
          {{ t('garage-overview__intro') }}
          <span v-if="totalUnread" class="font-semibold text-amber-700">
            {{ t('garage-overview__unread', totalUnread) }}
          </span>
        </p>
      </div>
      <router-link :to="{ name: 'book' }" class="rounded-xl bg-amber-400 px-5 py-2.5 text-center font-semibold text-slate-900 hover:bg-amber-300">
        {{ t('garage-overview__cta') }}
      </router-link>
    </div>

    <div v-if="loading" class="mt-8 space-y-4">
      <div v-for="n in 2" :key="n" class="h-48 animate-pulse rounded-2xl bg-slate-200/60" />
    </div>
    <p v-else-if="loadError" class="mt-8 rounded-xl bg-red-50 p-4 text-sm text-red-700">
      {{ t('garage-overview__load-error') }}
    </p>

    <div v-else-if="vehicles.length === 0 && requests.length === 0" class="mt-8 rounded-3xl bg-white p-10 text-center shadow-sm ring-1 ring-slate-200">
      <p class="text-lg font-semibold text-slate-900">{{ t('garage-empty__title') }}</p>
      <p class="mx-auto mt-2 max-w-md text-sm text-slate-600">{{ t('garage-empty__body') }}</p>
      <router-link :to="{ name: 'book' }" class="mt-6 inline-block rounded-xl bg-slate-900 px-5 py-2.5 font-semibold text-white hover:bg-slate-800">
        {{ t('garage-empty__cta') }}
      </router-link>
    </div>

    <template v-else>
      <section v-for="vehicle in vehicles" :key="vehicle.id" class="mt-8 overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
        <header class="flex flex-col gap-3 border-b border-slate-100 bg-slate-900 px-6 py-5 text-white sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0">
            <form v-if="editingId === vehicle.id" class="flex gap-2" @submit.prevent="saveRename(vehicle)">
              <input
                v-model="nicknameDraft"
                maxlength="60"
                :placeholder="t('garage-vehicle__nickname-placeholder')"
                class="min-w-0 rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-amber-400"
                :aria-label="t('garage-vehicle__nickname-label')"
              />
              <button type="submit" class="rounded-lg bg-amber-400 px-3 py-1.5 text-sm font-semibold text-slate-900">{{ t('garage-vehicle__nickname-save') }}</button>
              <button type="button" class="px-2 text-sm text-slate-400" @click="editingId = null">{{ t('garage-vehicle__nickname-cancel') }}</button>
            </form>
            <div v-else class="flex items-center gap-2">
              <h2 class="truncate text-lg font-semibold">{{ vehicle.label }}</h2>
              <button type="button" class="text-xs text-slate-400 hover:text-white" @click="startRename(vehicle)">{{ t('garage-vehicle__rename') }}</button>
            </div>
            <p class="mt-0.5 font-mono text-xs tracking-wider text-slate-400">
              <template v-if="vehicle.nickname">{{ vehicle.year }} {{ vehicle.make }} {{ vehicle.model }} · </template>VIN {{ vehicle.vin }}
            </p>
          </div>
          <router-link
            :to="{ name: 'book', query: { vin: vehicle.vin } }"
            class="shrink-0 rounded-lg border border-slate-600 px-3 py-1.5 text-sm font-semibold hover:border-slate-400 hover:bg-slate-800"
          >
            {{ t('garage-vehicle__book-cta') }}
          </router-link>
        </header>

        <dl class="grid grid-cols-3 divide-x divide-slate-100 border-b border-slate-100 text-center">
          <div class="px-3 py-3">
            <dt class="text-xs text-slate-500">{{ t('garage-vehicle__stat--visits') }}</dt>
            <dd class="font-semibold text-slate-900">{{ vehicle.history.length }}</dd>
          </div>
          <div class="px-3 py-3">
            <dt class="text-xs text-slate-500">{{ t('garage-vehicle__stat--last-service') }}</dt>
            <dd class="font-semibold text-slate-900">{{ lastCompleted(vehicle) ? formatDate(lastCompleted(vehicle)!.completed_on) : '—' }}</dd>
          </div>
          <div class="px-3 py-3">
            <dt class="text-xs text-slate-500">{{ t('garage-vehicle__stat--last-odometer') }}</dt>
            <dd class="font-semibold text-slate-900">{{ lastOdometer(vehicle)?.toLocaleString() ?? '—' }}</dd>
          </div>
        </dl>

        <ol class="divide-y divide-slate-100">
          <li v-for="r in vehicle.history" :key="r.id">
            <router-link :to="{ name: 'account-request', params: { id: r.id } }" class="flex items-center gap-4 px-6 py-4 hover:bg-slate-50">
              <div class="w-24 shrink-0 text-sm text-slate-500">{{ formatDate(serviceDate(r)) }}</div>
              <div class="min-w-0 flex-1">
                <p class="truncate font-medium text-slate-900">{{ servicesLabel(r.services) || t('garage-history__contact-request') }}</p>
                <p class="mt-0.5 text-xs text-slate-500">
                  <template v-if="r.final_total">{{ t('garage-history__paid', { amount: formatMoney(r.final_total) }) }}</template>
                  <template v-else-if="r.estimated_total">{{ t('garage-history__estimated', { amount: formatMoney(r.estimated_total) }) }}</template>
                  <template v-if="r.odometer"> · {{ t('garage-history__odometer', { miles: r.odometer.toLocaleString(intlLocale()) }) }}</template>
                </p>
              </div>
              <span v-if="unreadByRequest.get(r.id)" class="rounded-full bg-amber-400 px-2 py-0.5 text-xs font-bold text-slate-900">
                {{ t('garage-history__unread-badge', { count: unreadByRequest.get(r.id) }) }}
              </span>
              <StatusBadge :status="r.status" />
            </router-link>
          </li>
        </ol>
      </section>

      <section v-if="looseRequests.length" class="mt-8 rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
        <h2 class="border-b border-slate-100 px-6 py-4 font-semibold text-slate-900">{{ t('garage-other__title') }}</h2>
        <ol class="divide-y divide-slate-100">
          <li v-for="r in looseRequests" :key="r.id">
            <router-link :to="{ name: 'account-request', params: { id: r.id } }" class="flex items-center gap-4 px-6 py-4 hover:bg-slate-50">
              <div class="w-24 shrink-0 text-sm text-slate-500">{{ formatDate(r.created_at) }}</div>
              <p class="min-w-0 flex-1 truncate font-medium text-slate-900">
                {{ r.request_type === 'callback' ? t('garage-history__contact-request') : servicesLabel(r.services) }}
              </p>
              <span v-if="r.unread_count" class="rounded-full bg-amber-400 px-2 py-0.5 text-xs font-bold text-slate-900">{{ t('garage-history__unread-badge', { count: r.unread_count }) }}</span>
              <StatusBadge :status="r.status" />
            </router-link>
          </li>
        </ol>
      </section>
    </template>
  </div>
</template>
