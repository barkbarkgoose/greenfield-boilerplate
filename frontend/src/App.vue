<script setup lang="ts">
import { useRoute } from 'vue-router'
import Navbar from '@/components/Navbar.vue'

const route = useRoute()
</script>

<template>
  <div id="app" class="min-h-screen bg-gray-50">
    <!-- Public pages render their own header. -->
    <Navbar v-if="!route.meta.public" />
    <main>
      <router-view />
    </main>
  </div>
</template>
