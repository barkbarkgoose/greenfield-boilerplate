<script setup lang="ts">
// Dashboard - add your dashboard content here
</script>

<template>
  <div class="p-8">
    <h1 class="text-2xl font-bold text-gray-900">Dashboard</h1>
    <p class="mt-4 text-gray-600">Welcome to your dashboard. Start building your application features.</p>
    <div class="mt-6 flex flex-wrap gap-3">
      <!-- Booking and contact requests from the public intake form live in the Django admin. -->
      <a
        href="/admin/intake/servicerequest/"
        class="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
      >
        View service requests
      </a>
      <router-link
        to="/"
        class="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50"
      >
        View public site
      </router-link>
    </div>
  </div>
</template>
