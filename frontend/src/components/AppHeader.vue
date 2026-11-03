<script setup>
import { BookOpen, RadioTower } from "@lucide/vue";
</script>

<template>
  <header class="app-header">
    <RouterLink class="brand" to="/" aria-label="返回剧本大厅">
      <span class="brand-seal"><BookOpen :size="18" :stroke-width="1.8" /></span>
      <span class="brand-copy"><strong>幕间戏语</strong><small>AI 剧本空间</small></span>
    </RouterLink>
    <div class="header-center"><slot name="center" /></div>
    <div class="header-actions">
      <slot name="actions">
        <span class="service-pill"><RadioTower :size="15" />服务在线</span>
      </slot>
    </div>
  </header>
</template>
