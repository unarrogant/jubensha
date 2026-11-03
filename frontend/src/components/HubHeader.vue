<script setup>
import { BookOpen, RadioTower } from "@lucide/vue";

defineProps({
  title: { type: String, default: "幕间戏语" },
  subtitle: { type: String, default: "CURTAIN BETWEEN · AI 剧本空间" },
  compact: { type: Boolean, default: false },
});
</script>

<template>
  <header class="topbar" :class="{ compact }">
    <RouterLink class="brand" to="/" aria-label="返回剧本大厅">
      <span class="seal">幕</span>
      <span class="brand-copy"><strong>{{ title }}</strong><small>{{ subtitle }}</small></span>
    </RouterLink>
    <div class="header-center"><slot name="center" /></div>
    <div class="header-actions">
      <slot name="actions">
        <span class="pill"><span class="dot"></span>服务在线</span>
      </slot>
    </div>
  </header>
</template>

<style scoped>
.header-center { display: flex; align-items: center; gap: 22px; min-width: 0; }
.header-actions { display: flex; align-items: center; gap: 12px; }
</style>
