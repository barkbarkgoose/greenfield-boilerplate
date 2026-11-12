<script setup lang="ts">
import Navbar from '@/components/Navbar.vue'
import PasskeyPrompt from '@/components/PasskeyPrompt.vue'
</script>

<template>
  <div id="app" class="min-h-screen bg-gray-50">
    <Navbar />
    <main>
      <router-view />
    </main>
    <PasskeyPrompt />
  </div>
</template>
