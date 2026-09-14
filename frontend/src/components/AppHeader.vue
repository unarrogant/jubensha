<script setup>
import { RadioTower } from "@lucide/vue";
</script>

<template>
  <header class="app-header">
    <RouterLink class="brand" to="/" aria-label="返回剧本大厅">
      <span class="brand-seal">幕</span>
      <span class="brand-copy"><strong>幕间</strong><small>AI 剧本局</small></span>
    </RouterLink>
    <div class="header-center"><slot name="center" /></div>
    <div class="header-actions">
      <slot name="actions">
        <span class="service-pill"><RadioTower :size="15" />服务在线</span>
      </slot>
    </div>
  </header>
</template>
