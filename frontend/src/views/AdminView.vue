<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  Activity,
  ChevronRight,
  Database,
  LogOut,
  RefreshCw,
  ShieldCheck,
  Users,
  X,
} from "@lucide/vue";
import { getAdminRoom, getAdminRooms } from "../services/api";

const router = useRouter();
const token = localStorage.getItem("script_kill_admin_token");
const adminName = localStorage.getItem("script_kill_admin_username") || "管理员";
const rooms = ref([]);
const selectedRoom = ref(null);
const selectedRoomId = ref("");
const loading = ref(true);
const detailLoading = ref(false);
const refreshing = ref(false);
const errorMessage = ref("");
let refreshTimer = null;

const metrics = computed(() => ({
  total: rooms.value.length,
  waiting: rooms.value.filter((room) => room.status === "waiting").length,
  playing: rooms.value.filter((room) => ["playing", "active"].includes(room.status)).length,
  players: rooms.value.reduce((sum, room) => sum + Number(room.player_count || 0), 0),
}));

function formatStatus(status) {
  return {
    waiting: "等待中",
    playing: "进行中",
    active: "进行中",
    ended: "已结束",
  }[status] || status || "未知";
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function roomPlayers(room) {
  return Array.isArray(room?.players) ? room.players : [];
}

function roomMessages(room) {
  return Array.isArray(room?.messages) ? room.messages : [];
}

function roomVotes(room) {
  const votes = room?.game?.votes || room?.votes;
  return votes && typeof votes === "object" ? Object.entries(votes) : [];
}

function isUnauthorized(error) {
  return error?.message?.includes("401") || error?.message?.includes("登录") || error?.message?.includes("过期");
}

function signOut() {
  localStorage.removeItem("script_kill_admin_token");
  localStorage.removeItem("script_kill_admin_username");
  router.replace("/admin/login");
}

async function loadRooms({ quiet = false } = {}) {
  if (!quiet) loading.value = true;
  else refreshing.value = true;
  errorMessage.value = "";
  try {
    rooms.value = await getAdminRooms(token);
    if (selectedRoomId.value && !rooms.value.some((room) => room.id === selectedRoomId.value)) {
      selectedRoomId.value = "";
      selectedRoom.value = null;
    }
  } catch (error) {
    if (isUnauthorized(error)) return signOut();
    errorMessage.value = error.message || "房间数据加载失败";
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

async function selectRoom(roomId) {
  selectedRoomId.value = roomId;
  selectedRoom.value = null;
  detailLoading.value = true;
  errorMessage.value = "";
  try {
    selectedRoom.value = await getAdminRoom(roomId, token);
  } catch (error) {
    if (isUnauthorized(error)) return signOut();
    errorMessage.value = error.message || "房间详情加载失败";
  } finally {
    detailLoading.value = false;
  }
}

function closeDetail() {
  selectedRoomId.value = "";
  selectedRoom.value = null;
}

onMounted(() => {
  if (!token) return router.replace("/admin/login");
  loadRooms();
  refreshTimer = window.setInterval(() => loadRooms({ quiet: true }), 5000);
});

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer);
});
</script>

<template>
  <main class="admin-page">
    <header class="admin-header">
      <div class="admin-header-brand">
        <span class="admin-header-icon"><ShieldCheck :size="19" /></span>
        <div><strong>剧本杀管理后台</strong><small>运行数据与房间监控</small></div>
      </div>
      <div class="admin-header-actions">
        <span class="admin-user">{{ adminName }}</span>
        <button class="icon-text-button" type="button" :disabled="refreshing" @click="loadRooms({ quiet: true })">
          <RefreshCw :size="14" :class="{ spin: refreshing }" />刷新
        </button>
        <button class="icon-text-button" type="button" @click="signOut"><LogOut :size="14" />退出</button>
      </div>
    </header>

    <section class="admin-content">
      <div class="admin-page-intro">
        <div><span class="admin-eyebrow">OPERATIONS</span><h1>房间总览</h1><p>实时查看房间状态、玩家进度和主持流程数据。</p></div>
        <div class="admin-sync"><Activity :size="14" />每 5 秒同步</div>
      </div>
      <p v-if="errorMessage" class="admin-alert wide-admin-alert">{{ errorMessage }}</p>

      <div class="admin-metrics">
        <article><Database :size="17" /><span>全部房间</span><strong>{{ metrics.total }}</strong></article>
        <article><Activity :size="17" /><span>进行中</span><strong>{{ metrics.playing }}</strong></article>
        <article><Users :size="17" /><span>等待中</span><strong>{{ metrics.waiting }}</strong></article>
        <article><Users :size="17" /><span>在线玩家</span><strong>{{ metrics.players }}</strong></article>
      </div>

      <section class="admin-workspace">
        <div class="admin-room-table-wrap">
          <div class="admin-section-heading"><div><h2>房间列表</h2><span>{{ rooms.length }} 个记录</span></div></div>
          <div v-if="loading" class="admin-empty">正在读取房间数据...</div>
          <div v-else-if="!rooms.length" class="admin-empty">暂无房间记录</div>
          <div v-else class="admin-room-table">
            <button
              v-for="room in rooms"
              :key="room.id"
              class="admin-room-row"
              :class="{ selected: selectedRoomId === room.id }"
              type="button"
              @click="selectRoom(room.id)"
            >
              <span class="room-id">{{ room.id }}</span>
              <span class="room-script"><strong>{{ room.script_id || "未指定剧本" }}</strong><small>v{{ room.script_version || "-" }}</small></span>
              <span class="room-status" :data-status="room.status">{{ formatStatus(room.status) }}</span>
              <span class="room-capacity">{{ room.player_count || 0 }} / {{ room.required_players || "-" }} 人</span>
              <ChevronRight :size="16" />
            </button>
          </div>
        </div>

        <aside class="admin-detail-panel">
          <template v-if="selectedRoomId && detailLoading"><div class="admin-detail-loading">正在读取房间快照...</div></template>
          <template v-else-if="selectedRoom">
            <div class="admin-detail-heading">
              <div><span>ROOM SNAPSHOT</span><h2>{{ selectedRoom.id }}</h2></div>
              <button class="admin-close-button" type="button" aria-label="关闭详情" title="关闭详情" @click="closeDetail"><X :size="17" /></button>
            </div>
            <dl class="detail-facts">
              <div><dt>剧本</dt><dd>{{ selectedRoom.script_id }} / v{{ selectedRoom.script_version }}</dd></div>
              <div><dt>状态</dt><dd>{{ formatStatus(selectedRoom.status) }}</dd></div>
              <div><dt>创建时间</dt><dd>{{ formatDate(selectedRoom.created_at) }}</dd></div>
              <div><dt>当前阶段</dt><dd>{{ selectedRoom.game?.stage_id || "-" }}</dd></div>
            </dl>
            <div class="detail-section">
              <h3>玩家 <span>{{ roomPlayers(selectedRoom).length }}</span></h3>
              <div v-if="roomPlayers(selectedRoom).length" class="detail-player-list">
                <div v-for="player in roomPlayers(selectedRoom)" :key="player.id || player.name">
                  <strong>{{ player.name || player.id }}</strong>
                  <small>{{ player.character_name || player.character_id || "未分配角色" }}</small>
                </div>
              </div>
              <p v-else class="detail-muted">暂无玩家数据</p>
            </div>
            <div class="detail-stat-grid">
              <div><span>消息</span><strong>{{ roomMessages(selectedRoom).length }}</strong></div>
              <div><span>投票</span><strong>{{ roomVotes(selectedRoom).length }}</strong></div>
              <div><span>公共线索</span><strong>{{ selectedRoom.game?.public_clue_ids?.length || selectedRoom.public_clue_ids?.length || 0 }}</strong></div>
            </div>
            <details class="raw-snapshot"><summary>查看原始快照</summary><pre>{{ JSON.stringify(selectedRoom, null, 2) }}</pre></details>
          </template>
          <div v-else class="admin-detail-placeholder"><Database :size="23" /><strong>选择一个房间</strong><span>右侧显示完整运行快照</span></div>
        </aside>
      </section>
    </section>
  </main>
</template>

<style scoped>
.admin-page { min-height: 100vh; background: #eef1ee; }
.admin-header { min-height: 66px; padding: 0 34px; display: flex; align-items: center; justify-content: space-between; gap: 20px; color: #f7f8f7; background: var(--header); border-bottom: 1px solid #343c37; }
.admin-header-brand, .admin-header-actions, .admin-sync { display: flex; align-items: center; gap: 10px; }
.admin-header-brand small { display: block; margin-top: 4px; color: #aeb7b1; font-size: 9px; }
.admin-header-brand strong { font-size: 14px; }
.admin-header-icon { display: grid; place-items: center; width: 34px; height: 34px; color: #fff; background: var(--red); border-radius: 4px; }
.admin-header-actions .icon-text-button { min-height: 34px; color: #d7ded9; background: #29312c; border-color: #414b44; }
.admin-header-actions .icon-text-button:hover:not(:disabled) { color: #fff; border-color: #82958a; }
.admin-user { color: #aeb7b1; font-size: 11px; }
.admin-content { width: min(1280px, calc(100% - 48px)); margin: 0 auto; padding: 42px 0 70px; }
.admin-page-intro { display: flex; align-items: end; justify-content: space-between; gap: 20px; padding-bottom: 24px; border-bottom: 1px solid var(--line); }
.admin-eyebrow { color: var(--red); font-size: 10px; font-weight: 800; letter-spacing: .08em; }
.admin-page-intro h1 { margin: 7px 0; font-family: Georgia, "Songti SC", serif; font-size: 34px; font-weight: 600; }
.admin-page-intro p { margin: 0; color: var(--muted); font-size: 13px; }
.admin-sync { min-height: 32px; padding: 0 10px; color: var(--muted); background: #f8faf8; border: 1px solid var(--line); border-radius: 4px; font-size: 10px; }
.admin-alert { padding: 10px 12px; color: #74272d; background: var(--red-soft); border: 1px solid #e5bdc0; border-radius: 4px; font-size: 11px; }
.wide-admin-alert { margin: 18px 0 0; }
.admin-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 22px 0; }
.admin-metrics article { display: grid; grid-template-columns: 25px 1fr; align-items: center; column-gap: 8px; min-height: 86px; padding: 15px 17px; background: #fff; border: 1px solid var(--line); border-radius: 5px; }
.admin-metrics svg { grid-row: 1 / span 2; color: var(--green); }
.admin-metrics span { color: var(--muted); font-size: 10px; }
.admin-metrics strong { margin-top: 4px; font-family: Georgia, serif; font-size: 27px; line-height: 1; }
.admin-workspace { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(330px, .65fr); gap: 14px; align-items: start; }
.admin-room-table-wrap, .admin-detail-panel { min-width: 0; background: #fff; border: 1px solid var(--line); border-radius: 5px; }
.admin-section-heading { min-height: 67px; padding: 14px 17px; border-bottom: 1px solid var(--line); }
.admin-section-heading h2 { margin: 0 0 4px; font-size: 16px; }
.admin-section-heading span { color: var(--muted); font-size: 10px; }
.admin-room-table { display: grid; }
.admin-room-row { display: grid; grid-template-columns: 105px minmax(140px, 1fr) 70px 85px 18px; align-items: center; gap: 14px; min-height: 70px; padding: 10px 16px; color: var(--ink); background: #fff; border: 0; border-bottom: 1px solid #edf0ee; text-align: left; }
.admin-room-row:hover, .admin-room-row.selected { background: #f3f7f4; }
.admin-room-row svg { color: var(--faint); }
.room-id { overflow: hidden; color: var(--green-strong); font-family: Consolas, monospace; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.room-script, .room-script small { display: block; min-width: 0; }
.room-script strong { display: block; overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.room-script small { margin-top: 4px; color: var(--muted); font-size: 9px; }
.room-status { justify-self: start; padding: 4px 6px; color: #58645c; background: #edf1ee; border-radius: 3px; font-size: 10px; white-space: nowrap; }
.room-status[data-status="playing"], .room-status[data-status="active"] { color: #275c43; background: #e5f1e9; }
.room-capacity { color: var(--muted); font-size: 10px; white-space: nowrap; }
.admin-empty, .admin-detail-loading { min-height: 180px; display: grid; place-items: center; color: var(--muted); font-size: 12px; }
.admin-detail-panel { min-height: 420px; padding: 17px; }
.admin-detail-heading { display: flex; align-items: start; justify-content: space-between; gap: 10px; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.admin-detail-heading span { color: var(--red); font-size: 9px; font-weight: 800; letter-spacing: .07em; }
.admin-detail-heading h2 { margin: 5px 0 0; font-family: Consolas, monospace; font-size: 18px; }
.admin-close-button { display: grid; place-items: center; width: 30px; height: 30px; color: var(--muted); background: transparent; border: 1px solid var(--line); border-radius: 4px; }
.detail-facts { margin: 0; }
.detail-facts > div { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid #edf0ee; }
.detail-facts dt { color: var(--muted); font-size: 10px; }
.detail-facts dd { max-width: 68%; margin: 0; overflow: hidden; font-size: 10px; font-weight: 700; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.detail-section { padding: 15px 0; border-bottom: 1px solid var(--line); }
.detail-section h3 { display: flex; justify-content: space-between; margin: 0 0 9px; font-size: 11px; }
.detail-section h3 span { color: var(--muted); font-weight: 400; }
.detail-player-list { display: grid; gap: 7px; }
.detail-player-list div { display: flex; justify-content: space-between; gap: 10px; padding: 7px 8px; background: #f6f8f6; border-left: 2px solid var(--green); }
.detail-player-list strong, .detail-player-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-player-list strong { font-size: 10px; }
.detail-player-list small { color: var(--muted); font-size: 9px; }
.detail-muted { margin: 0; color: var(--muted); font-size: 10px; }
.detail-stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; padding: 15px 0; }
.detail-stat-grid div { padding: 9px; background: #f6f8f6; }
.detail-stat-grid span, .detail-stat-grid strong { display: block; }
.detail-stat-grid span { color: var(--muted); font-size: 9px; }
.detail-stat-grid strong { margin-top: 4px; font-size: 16px; }
.raw-snapshot { border-top: 1px solid var(--line); padding-top: 12px; }
.raw-snapshot summary { color: var(--green); cursor: pointer; font-size: 10px; font-weight: 700; }
.raw-snapshot pre { max-height: 260px; overflow: auto; margin: 10px 0 0; padding: 10px; color: #4e5a52; background: #f4f6f4; font-size: 9px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.admin-detail-placeholder { min-height: 385px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 9px; color: var(--faint); text-align: center; }
.admin-detail-placeholder strong { color: var(--muted); font-size: 12px; }
.admin-detail-placeholder span { font-size: 10px; }
.spin { animation: admin-spin 850ms linear infinite; }
@keyframes admin-spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .admin-workspace { grid-template-columns: 1fr; } .admin-detail-panel { min-height: 260px; } .admin-detail-placeholder { min-height: 220px; } }
@media (max-width: 650px) { .admin-header { padding: 0 16px; } .admin-header-actions .icon-text-button { padding: 0 8px; } .admin-user { display: none; } .admin-content { width: calc(100% - 28px); padding-top: 28px; } .admin-page-intro { display: block; } .admin-sync { width: max-content; margin-top: 16px; } .admin-metrics { grid-template-columns: repeat(2, 1fr); } .admin-room-row { grid-template-columns: 82px minmax(0, 1fr) 65px 18px; gap: 8px; } .room-capacity { display: none; } }
</style>
