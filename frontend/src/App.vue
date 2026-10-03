<script setup lang="ts">
import SiteHeader from '@/components/SiteHeader.vue'
import SiteFooter from '@/components/SiteFooter.vue'
</script>

<template>
  <!-- One header and footer for every page, signed in or not. -->
  <div id="app" class="flex min-h-screen flex-col bg-slate-50">
    <SiteHeader />
    <!-- Pages fill the width; flex lets short pages (sign in) center vertically. -->
    <main class="flex flex-1 flex-col *:w-full">
      <router-view />
    </main>
    <SiteFooter />
  </div>
</template>
