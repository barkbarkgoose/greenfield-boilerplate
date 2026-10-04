<script setup lang="ts">
// The signed-in user's passkeys: add a backup (e.g. a phone as well as
// Bitwarden) or remove one. Shown on Settings for accounts that require one.
import { onMounted, ref } from 'vue'
import axios from 'axios'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { createPasskey, deletePasskey, isPasskeyCancelled, listPasskeys } from '@/services/passkeys'
import type { Passkey } from '@/services/passkeys'
import { formatDate } from '@/utils/format'

const { t } = useI18n()
const authStore = useAuthStore()

const passkeys = ref<Passkey[]>([])
const required = ref(false)
const newName = ref('')
const busy = ref(false)
const errorMessage = ref('')

async function load() {
  const data = await listPasskeys()
  passkeys.value = data.passkeys
  required.value = data.required
}

async function add() {
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await createPasskey(newName.value.trim() || 'Passkey')
    authStore.completePasskeyLogin(result)
    newName.value = ''
    await load()
  } catch (error) {
    errorMessage.value = isPasskeyCancelled(error) ? t('passkey-setup__error--cancelled') : t('passkey-setup__error--generic')
  } finally {
    busy.value = false
  }
}

async function remove(passkey: Passkey) {
  if (!window.confirm(t('passkey-manager__remove-confirm', { name: passkey.name }))) return
  busy.value = true
  errorMessage.value = ''
  try {
    await deletePasskey(passkey.id)
    await load()
  } catch (error) {
    errorMessage.value =
      axios.isAxiosError(error) && error.response?.status === 400
        ? t('passkey-manager__error--last')
        : t('passkey-setup__error--generic')
  } finally {
    busy.value = false
  }
}

onMounted(() => load().catch(() => (errorMessage.value = t('passkey-setup__error--generic'))))
</script>

<template>
  <div class="passkey-manager">
    <p class="text-sm text-stone-500">{{ required ? t('passkey-manager__intro--required') : t('passkey-manager__intro') }}</p>
    <ul v-if="passkeys.length" class="mt-4 divide-y divide-stone-100 rounded-xl ring-1 ring-stone-200">
      <li v-for="passkey in passkeys" :key="passkey.id" class="flex items-center justify-between gap-3 px-4 py-3 text-sm">
        <span class="min-w-0">
          <span class="block truncate font-medium text-stone-900">{{ passkey.name }}</span>
          <span class="block text-xs text-stone-500">
            {{ t('passkey-manager__added', { date: formatDate(passkey.created_at) }) }}
            <template v-if="passkey.last_used_at"> · {{ t('passkey-manager__last-used', { date: formatDate(passkey.last_used_at) }) }}</template>
          </span>
        </span>
        <button type="button" :disabled="busy" class="shrink-0 text-xs font-semibold text-stone-500 hover:text-red-700 disabled:opacity-50" @click="remove(passkey)">
          {{ t('passkey-manager__remove') }}
        </button>
      </li>
    </ul>
    <form class="mt-4 flex flex-col gap-2 sm:flex-row" @submit.prevent="add">
      <label for="new-passkey-name" class="sr-only">{{ t('passkey-setup__name-label') }}</label>
      <input
        id="new-passkey-name"
        v-model="newName"
        type="text"
        maxlength="60"
        :placeholder="t('passkey-manager__name-placeholder')"
        class="min-w-0 flex-1 rounded-xl border border-stone-300 px-3 py-2 text-sm focus:border-lime-500 focus:outline-none focus:ring-2 focus:ring-lime-400/40"
      />
      <button type="submit" :disabled="busy" class="rounded-xl bg-stone-900 px-4 py-2 text-sm font-semibold text-white hover:bg-stone-800 disabled:opacity-50">
        {{ t('passkey-manager__add') }}
      </button>
    </form>
    <p v-if="errorMessage" class="mt-2 text-sm text-red-700" role="alert">{{ errorMessage }}</p>
  </div>
</template>
