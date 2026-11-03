<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  AlertTriangle,
  ArrowUpDown,
  Bot,
  BookOpen,
  Copy,
  Database,
  Download,
  LayoutDashboard,
  LogOut,
  RefreshCw,
  Search,
  Trash2,
  Users,
  X,
} from "@lucide/vue";
import { useAdminStore } from "../stores/admin";

const TOKEN_KEY = "script_kill_admin_token";

const STAGE_CN = {
  waiting: "等待入席",
  role_selection: "角色分配",
  intro: "自我介绍",
  investigation: "搜证",
  discussion: "讨论推理",
  voting: "最终投票",
  ending: "最终复盘",
};
const STAGE_FLOW = Object.keys(STAGE_CN);
const STATUS_CN = { waiting: "等待中", playing: "进行中", active: "进行中", ended: "已结束" };
const VIEWS = [
  { key: "overview", label: "总览", icon: LayoutDashboard, sub: "整个平台的运行状况一眼看完" },
  { key: "rooms", label: "房间", icon: Database, sub: "点任意一行查看这一局的完整数据" },
  { key: "ai", label: "AI 运行", icon: Bot, sub: "主持人的每一次生成、工具调用与失败都在这里" },
  { key: "scripts", label: "剧本", icon: BookOpen, sub: "按剧本聚合，看哪套真的被玩完" },
];
const TABS = [
  { key: "summary", label: "概览" },
  { key: "players", label: "玩家" },
  { key: "events", label: "事件流" },
  { key: "ai", label: "AI 审计" },
  { key: "peer", label: "互评" },
];
const COLUMNS = [
  { key: "id", label: "房间" },
  { key: "scriptId", label: "剧本" },
  { key: "status", label: "状态" },
  { key: "stageId", label: "阶段" },
  { key: "playerCount", label: "玩家" },
  { key: "eventCount", label: "事件" },
  { key: "aiRequests", label: "AI 请求" },
  { key: "updatedAt", label: "更新" },
];

const router = useRouter();
const adminStore = useAdminStore();

const view = ref("overview");
const query = ref("");
const statusFilter = ref("all");
const runFilter = ref("all");
const sortState = ref({ key: "updatedAt", dir: -1 });
const drawerTab = ref("summary");
const eventFilter = ref("all");
const openPlayerId = ref("");
const drawerOpen = ref(false);
const actionBusy = ref(false);
const toastText = ref("");
let toastTimer = null;
let pollTimer = null;

const rooms = computed(() => adminStore.rooms);
const selectedRoom = computed(() => adminStore.selectedRoom);
const auditOfSelected = computed(() =>
  selectedRoom.value ? adminStore.audits[selectedRoom.value.id] : null,
);
const currentView = computed(() => VIEWS.find((item) => item.key === view.value) || VIEWS[0]);

function count(key) {
  if (key === "ai") return adminStore.runCount;
  if (key === "scripts") return adminStore.scriptCount;
  return rooms.value.length;
}

function num(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

function stageCn(id) {
  return STAGE_CN[id] || id || "—";
}

function statusCn(status) {
  return STATUS_CN[status] || status || "未知";
}

function shortTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function fullTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function snapshotLabel() {
  if (!adminStore.snapshotAt) return "正在读取…";
  return `快照 ${new Date(adminStore.snapshotAt).toLocaleTimeString("zh-CN", { hour12: false })}`;
}

function matches(room) {
  if (statusFilter.value !== "all" && room.status !== statusFilter.value) return false;
  const text = query.value.trim().toLowerCase();
  if (!text) return true;
  const haystack = [
    room.id,
    room.scriptId,
    room.stageId,
    ...room.players.map((player) => `${player.name} ${player.characterId || ""}`),
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(text);
}

const visibleRooms = computed(() => {
  const key = sortState.value.key;
  const dir = sortState.value.dir;
  return rooms.value
    .filter(matches)
    .slice()
    .sort((left, right) => String(left[key] ?? "").localeCompare(String(right[key] ?? ""), "zh", { numeric: true }) * dir);
});

const kpis = computed(() => {
  const list = rooms.value;
  const waiting = list.filter((room) => room.status === "waiting").length;
  const playing = list.filter((room) => ["playing", "active"].includes(room.status)).length;
  const ended = list.filter((room) => room.status === "ended").length;
  const failed = list.reduce((sum, room) => sum + room.failedRuns + room.toolFailed, 0);
  return [
    { label: "房间总数", value: num(list.length), note: "含进行中与已结束" },
    { label: "进行中", value: num(playing), note: `等待 ${waiting} · 结束 ${ended}`, cls: "good" },
    { label: "玩家总数", value: num(list.reduce((sum, room) => sum + room.playerCount, 0)), note: "全部席位相加" },
    { label: "AI 请求", value: num(list.reduce((sum, room) => sum + room.aiRequests, 0)), note: `工具调用 ${num(list.reduce((sum, room) => sum + room.toolCalls, 0))}` },
    { label: "异常", value: num(failed), note: failed ? "失败运行 + 工具错误" : "暂无失败记录", cls: failed ? "alert" : "" },
    { label: "线索发放", value: num(list.reduce((sum, room) => sum + room.clueCount, 0)), note: "公开线索同步全员" },
  ];
});

const eventFeed = computed(() =>
  rooms.value
    .flatMap((room) => room.events.map((event) => ({ ...event, roomId: room.id })))
    .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")))
    .slice(0, 14),
);

const scriptRows = computed(() => {
  const ids = [...new Set(rooms.value.map((room) => room.scriptId).filter(Boolean))];
  return ids.map((scriptId) => {
    const list = rooms.value.filter((room) => room.scriptId === scriptId);
    return {
      scriptId,
      version: list[0].scriptVersion,
      rooms: list.length,
      live: list.filter((room) => ["playing", "active"].includes(room.status)).length,
      people: list.reduce((sum, room) => sum + room.playerCount, 0),
      events: list.reduce((sum, room) => sum + room.eventCount, 0),
      clues: list.reduce((sum, room) => sum + room.clueCount, 0),
      requests: list.reduce((sum, room) => sum + room.aiRequests, 0),
      failures: list.reduce((sum, room) => sum + room.failedRuns + room.toolFailed, 0),
    };
  });
});
const maxScriptEvents = computed(() => Math.max(1, ...scriptRows.value.map((row) => row.events)));
const maxRoomEvents = computed(() => Math.max(1, ...visibleRooms.value.map((room) => room.eventCount)));

const allRuns = computed(() => {
  const list = rooms.value
    .flatMap((room) => room.runs.map((run) => ({ ...run, roomId: room.id, scriptId: room.scriptId })))
    .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")));
  return runFilter.value === "all" ? list : list.filter((run) => run.status === runFilter.value);
});

const recentAudits = computed(() =>
  adminStore
    .auditEntries()
    .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")))
    .slice(0, 12),
);

const statusOptions = computed(() => ["all", ...new Set(rooms.value.map((room) => room.status))]);
const runOptions = computed(() => [
  "all",
  ...new Set(rooms.value.flatMap((room) => room.runs.map((run) => run.status))),
]);
const selectedEventTypes = computed(() => [
  "all",
  ...new Set((selectedRoom.value?.events || []).map((event) => event.event_type)),
]);
const selectedEvents = computed(() => {
  const events = [...(selectedRoom.value?.events || [])].reverse();
  return eventFilter.value === "all"
    ? events
    : events.filter((event) => event.event_type === eventFilter.value);
});
const peerRows = computed(() =>
  Object.entries(selectedRoom.value?.peerReviews || {}).map(([voterId, review]) => ({
    voterId,
    bestSpeakerId: review.best_speaker_id,
    bestReasonerId: review.best_reasoner_id,
  })),
);
const voteRows = computed(() => {
  const distribution = selectedRoom.value?.voteDistribution || {};
  const max = Math.max(1, ...Object.values(distribution));
  return Object.entries(distribution).map(([target, votes]) => ({ target, votes, max }));
});

function nameOf(room, playerId) {
  if (!playerId) return "—";
  const player = room?.players.find((item) => item.id === playerId);
  if (!player) return playerId;
  return player.characterId ? `${player.name} · ${player.characterId}` : player.name;
}

function eventText(event) {
  const payload = event.payload || {};
  return (
    payload.message ||
    payload.content ||
    payload.clue_id ||
    payload.location_id ||
    payload.object_text ||
    payload.reason ||
    payload.suspect_id ||
    payload.stage_id ||
    JSON.stringify(payload)
  );
}

function barStyle(value, max) {
  return { width: `${max ? Math.round((Number(value) / max) * 100) : 0}%` };
}

function toast(text) {
  toastText.value = text;
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toastText.value = "";
  }, 2400);
}

function go(key) {
  view.value = key;
  eventFilter.value = "all";
  if (key === "ai") {
    // 问答审计按房间单独一个接口，切到这个视图才补齐，避免每次轮询都全量拉。
    rooms.value.forEach((room) => adminStore.loadAudit(room.id));
  }
}

function sortBy(key) {
  if (sortState.value.key === key) {
    sortState.value = { key, dir: sortState.value.dir * -1 };
  } else {
    sortState.value = { key, dir: 1 };
  }
}

function onSearch() {
  if (query.value.trim() && view.value === "overview") view.value = "rooms";
}

async function openRoom(room) {
  adminStore.select(room.id);
  drawerTab.value = "summary";
  eventFilter.value = "all";
  openPlayerId.value = "";
  drawerOpen.value = true;
  await adminStore.load();
}

function closeDrawer() {
  drawerOpen.value = false;
  adminStore.select("");
  openPlayerId.value = "";
}

async function setTab(key) {
  drawerTab.value = key;
  if (key === "ai" && selectedRoom.value) await adminStore.loadAudit(selectedRoom.value.id);
}

async function togglePlayer(playerId) {
  if (openPlayerId.value === playerId) {
    openPlayerId.value = "";
    return;
  }
  openPlayerId.value = playerId;
  if (selectedRoom.value) await adminStore.loadPlayerHistory(selectedRoom.value.id, playerId);
}

function playerHistory(playerId) {
  return adminStore.histories[`${selectedRoom.value?.id}:${playerId}`] || null;
}

function runPillClass(status) {
  return status === "succeeded" ? "ok" : "failed";
}

function toolPillClass(entry) {
  return /completed|success|already_triggered/.test(entry.tool_status || "") ? "ok" : "failed";
}

async function copyRoomId() {
  if (!selectedRoom.value) return;
  try {
    await navigator.clipboard.writeText(selectedRoom.value.id);
    toast("已复制房间号");
  } catch {
    toast("浏览器拒绝了剪贴板权限");
  }
}

async function exportRoom() {
  if (!selectedRoom.value || actionBusy.value) return;
  actionBusy.value = true;
  try {
    await adminStore.downloadExport(selectedRoom.value.id);
    toast("已导出这一局的完整 JSON");
  } catch (error) {
    toast(error.message || "导出失败");
  } finally {
    actionBusy.value = false;
  }
}

async function removeRoom() {
  const room = selectedRoom.value;
  if (!room || actionBusy.value) return;
  if (!window.confirm(`确定永久删除房间 ${room.id} 及其全部历史记录吗？此操作不可恢复。`)) return;
  actionBusy.value = true;
  try {
    await adminStore.removeRoom(room.id);
    closeDrawer();
    toast(`房间 ${room.id} 已删除`);
  } catch (error) {
    toast(error.message || "删除失败");
  } finally {
    actionBusy.value = false;
  }
}

function signOut() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem("script_kill_admin_username");
  router.replace("/admin/login");
}

function onKeydown(event) {
  if (event.key === "Escape" && drawerOpen.value) closeDrawer();
}

watch(
  () => adminStore.authFailed,
  (failed) => {
    if (failed) signOut();
  },
);

onMounted(() => {
  if (!localStorage.getItem(TOKEN_KEY)) return router.replace("/admin/login");
  adminStore.load();
  pollTimer = window.setInterval(() => adminStore.load(), 8000);
  document.addEventListener("keydown", onKeydown);
});

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
  if (toastTimer) window.clearTimeout(toastTimer);
  document.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <main class="admin">
    <aside class="side">
      <div class="brand">
        <div class="m">幕</div>
        <div><b>幕间戏语</b><span>Ops Console</span></div>
      </div>
      <nav class="nav">
        <button
          v-for="item in VIEWS"
          :key="item.key"
          type="button"
          :class="{ on: view === item.key }"
          @click="go(item.key)"
        >
          <component :is="item.icon" :size="15" />
          {{ item.label }}
          <em>{{ num(count(item.key)) }}</em>
        </button>
      </nav>
      <div class="side-foot">
        <div class="snap">{{ snapshotLabel() }}</div>
        <button class="ghost" type="button" @click="signOut"><LogOut :size="14" /> 退出登录</button>
      </div>
    </aside>

    <div class="main">
      <div class="top">
        <div>
          <h1>{{ currentView.label }}</h1>
          <div class="sub">
            <template v-if="view === 'rooms'">{{ visibleRooms.length }} / {{ rooms.length }} 间 · </template>{{ currentView.sub }}
          </div>
        </div>
        <div class="sp"></div>
        <label class="search">
          <Search :size="14" style="color: var(--faint)" />
          <input v-model="query" placeholder="搜索房间号 / 剧本 / 玩家" @input="onSearch" />
        </label>
        <div class="filters">
          <template v-if="view === 'rooms'">
            <button
              v-for="option in statusOptions"
              :key="option"
              type="button"
              class="chip"
              :class="{ on: statusFilter === option }"
              @click="statusFilter = option"
            >{{ option === "all" ? "全部" : statusCn(option) }}</button>
          </template>
          <template v-else-if="view === 'ai'">
            <button
              v-for="option in runOptions"
              :key="option"
              type="button"
              class="chip"
              :class="{ on: runFilter === option }"
              @click="runFilter = option"
            >{{ option === "all" ? "全部" : option }}</button>
          </template>
        </div>
        <button class="primary" type="button" :disabled="adminStore.refreshing" @click="adminStore.load()">
          <RefreshCw :size="14" :class="{ spin: adminStore.refreshing }" />重新读取
        </button>
      </div>

      <div class="body">
        <p v-if="adminStore.error" class="alert">
          <AlertTriangle :size="15" />{{ adminStore.error }}
        </p>
        <p v-else-if="adminStore.detailFailedIds.length" class="alert">
          <AlertTriangle :size="15" />{{ adminStore.detailFailedIds.join("、") }} 的完整快照没读到，只显示汇总数字。
        </p>

        <!-- 总览 -->
        <template v-if="view === 'overview'">
          <div class="kpis">
            <div v-for="card in kpis" :key="card.label" class="kpi" :class="card.cls">
              <span>{{ card.label }}</span><b>{{ card.value }}</b><small>{{ card.note }}</small>
            </div>
          </div>
          <div class="grid2">
            <div class="card">
              <header><h2>最近事件</h2><div class="sp"></div><em>{{ eventFeed.length }} 条 · 跨房间</em></header>
              <div class="feed">
                <div v-for="event in eventFeed" :key="event.id" class="ev">
                  <time>{{ shortTime(event.created_at) }}</time>
                  <span class="t">{{ event.event_type }}</span>
                  <p :title="event.roomId">{{ eventText(event) }}</p>
                  <span class="pill">{{ (event.roomId || "").slice(0, 4) }}</span>
                </div>
                <div v-if="!eventFeed.length" class="empty"><b>暂无事件</b>开一局游戏后这里会实时铺开。</div>
              </div>
            </div>
            <div class="stack">
              <div class="card">
                <header><h2>剧本分布</h2><div class="sp"></div><em>{{ adminStore.scriptCount }} 套</em></header>
                <div class="in">
                  <div v-for="row in scriptRows" :key="row.scriptId" class="kv">
                    <span>{{ row.scriptId }} <small style="color: var(--faint)">v{{ row.version }}</small></span>
                    <b>{{ row.rooms }} 间 · {{ row.people }} 人 · {{ num(row.events) }} 事件</b>
                  </div>
                  <div v-if="!scriptRows.length" class="empty">还没有房间</div>
                </div>
              </div>
              <div class="card">
                <header><h2>主持响应延迟</h2><div class="sp"></div><em>p50 / p95</em></header>
                <div class="in">
                  <div v-for="room in rooms.filter((item) => item.runs.length)" :key="room.id" class="kv">
                    <span>{{ room.id }} · {{ room.scriptId }}</span>
                    <b>
                      {{ room.p50 != null ? Math.round(room.p50) + "ms" : "—" }}
                      <small style="color: var(--faint); font-family: var(--mono)">p95 {{ room.p95 != null ? Math.round(room.p95) : "—" }}</small>
                    </b>
                  </div>
                  <div v-if="!rooms.some((item) => item.runs.length)" class="empty"><b>还没有 AI 运行记录</b></div>
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- 房间 -->
        <template v-else-if="view === 'rooms'">
          <div class="card">
            <header><h2>房间列表</h2><div class="sp"></div><em>{{ visibleRooms.length }} / {{ rooms.length }}</em></header>
            <div v-if="adminStore.loading" class="empty">正在读取房间数据…</div>
            <div v-else-if="!visibleRooms.length" class="empty"><b>没有符合条件的房间</b>换个关键词或清空状态筛选。</div>
            <table v-else>
              <thead>
                <tr>
                  <th
                    v-for="column in COLUMNS"
                    :key="column.key"
                    :class="{ sorted: sortState.key === column.key }"
                    @click="sortBy(column.key)"
                  >
                    {{ column.label }}<template v-if="sortState.key === column.key">{{ sortState.dir < 0 ? " ↓" : " ↑" }}</template>
                    <ArrowUpDown v-else :size="11" style="opacity:.45" />
                  </th>
                  <th class="no"></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="room in visibleRooms" :key="room.id" class="clickable" @click="openRoom(room)">
                  <td>
                    <span class="id">{{ room.id }}</span>
                    <span v-if="room.archived" class="pill ended">归档</span>
                  </td>
                  <td>{{ room.scriptId }} <small style="color: var(--faint)">v{{ room.scriptVersion }}</small></td>
                  <td><span class="pill" :class="room.status">{{ statusCn(room.status) }}</span></td>
                  <td>{{ stageCn(room.stageId) }}</td>
                  <td>
                    <div class="rowflex">
                      <span class="num">{{ room.playerCount }}/{{ room.requiredPlayers }}</span>
                      <div class="bar"><i :style="barStyle(room.playerCount, room.requiredPlayers)"></i></div>
                    </div>
                  </td>
                  <td>
                    <div class="rowflex">
                      <span class="num">{{ num(room.eventCount) }}</span>
                      <div class="bar gold"><i :style="barStyle(room.eventCount, maxRoomEvents)"></i></div>
                    </div>
                  </td>
                  <td class="num">
                    {{ num(room.aiRequests) }}
                    <span v-if="room.failedRuns" class="pill failed">{{ room.failedRuns }}</span>
                  </td>
                  <td>{{ fullTime(room.updatedAt || room.createdAt) }}</td>
                  <td><span class="pill">详情 →</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <!-- AI 运行 -->
        <template v-else-if="view === 'ai'">
          <div class="grid2">
            <div class="card">
              <header><h2>运行记录</h2><div class="sp"></div><em>{{ allRuns.length }} 次 · 状态可在右上角筛选</em></header>
              <table v-if="allRuns.length">
                <thead>
                  <tr>
                    <th class="no">时间</th><th class="no">房间</th><th class="no">类型</th>
                    <th class="no">阶段</th><th class="no">状态</th><th class="no">延迟</th><th class="no">Token</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(run, index) in allRuns" :key="`${run.roomId}-${run.id}-${index}`">
                    <td>{{ fullTime(run.created_at) }}</td>
                    <td><span class="id">{{ (run.roomId || "").slice(0, 8) }}</span></td>
                    <td>{{ run.request_type || "—" }}</td>
                    <td>{{ stageCn(run.stage_id) }}</td>
                    <td>
                      <span class="pill" :class="runPillClass(run.status)">{{ run.status }}</span>
                      <div v-if="run.error_code" style="font-size: 10.5px; color: var(--warn); margin-top: 3px">{{ run.error_code }}</div>
                    </td>
                    <td class="num">{{ run.elapsed_ms != null ? Math.round(run.elapsed_ms) + "ms" : "—" }}</td>
                    <td class="num">{{ num((run.input_tokens || 0) + (run.output_tokens || 0)) }}</td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="empty"><b>没有 AI 运行记录</b>玩家与主持人对话后才会产生。</div>
            </div>
            <div class="card">
              <header><h2>最近问答审计</h2><div class="sp"></div><em>{{ recentAudits.length }} 条</em></header>
              <div class="in scroll">
                <div v-for="entry in recentAudits" :key="`${entry.roomId}-${entry.id}`" class="qa">
                  <p class="q">{{ entry.question || "（无提问文字）" }}</p>
                  <p class="a">{{ entry.answer || "（无回答文字）" }}</p>
                  <div class="f">
                    <span class="pill" :class="entry.visibility === 'public' ? '' : 'ok'">{{ entry.visibility === "public" ? "公开" : "仅本人" }}</span>
                    <span v-if="entry.tool_used" class="pill" :class="toolPillClass(entry)">{{ entry.tool_name || "tool" }}</span>
                    <span v-if="entry.clue_ids?.length" class="pill">{{ entry.clue_ids.length }} 条线索</span>
                    <small>{{ entry.player_name || entry.player_id }} · {{ (entry.roomId || "").slice(0, 8) }}</small>
                  </div>
                </div>
                <div v-if="!recentAudits.length" class="empty">暂无审计条目</div>
              </div>
            </div>
          </div>
        </template>

        <!-- 剧本 -->
        <template v-else>
          <div class="card">
            <header><h2>按剧本汇总</h2><div class="sp"></div><em>{{ scriptRows.length }} 套剧本</em></header>
            <table v-if="scriptRows.length">
              <thead>
                <tr>
                  <th class="no">剧本</th><th class="no">房间</th><th class="no">进行中</th><th class="no">玩家</th>
                  <th class="no">事件</th><th class="no">线索</th><th class="no">AI 请求</th><th class="no">异常</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in scriptRows"
                  :key="row.scriptId"
                  class="clickable"
                  @click="statusFilter = 'all'; query = row.scriptId; go('rooms')"
                >
                  <td><b>{{ row.scriptId }}</b> <small style="color: var(--faint)">v{{ row.version }}</small></td>
                  <td class="num">{{ row.rooms }}</td>
                  <td class="num">{{ row.live }}</td>
                  <td class="num">{{ row.people }}</td>
                  <td>
                    <div class="rowflex">
                      <span class="num">{{ num(row.events) }}</span>
                      <div class="bar"><i :style="barStyle(row.events, maxScriptEvents)"></i></div>
                    </div>
                  </td>
                  <td class="num">{{ row.clues }}</td>
                  <td class="num">{{ row.requests }}</td>
                  <td>
                    <span v-if="row.failures" class="pill failed">{{ row.failures }}</span>
                    <span v-else class="pill ok">正常</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty"><b>还没有房间</b>开一局之后才有剧本数据。</div>
          </div>
        </template>
      </div>
    </div>

    <div class="scrim" :class="{ on: drawerOpen }" @click="closeDrawer"></div>
    <section v-if="selectedRoom" class="drawer" :class="{ on: drawerOpen }" aria-label="房间详情">
      <header>
        <div class="sp">
          <h2>{{ selectedRoom.id }} · {{ selectedRoom.scriptId }}</h2>
          <div class="meta">
            {{ statusCn(selectedRoom.status) }} · {{ stageCn(selectedRoom.stageId) }} ·
            {{ selectedRoom.playerCount }}/{{ selectedRoom.requiredPlayers }} 人 · {{ fullTime(selectedRoom.createdAt) }} 创建
          </div>
        </div>
        <button class="x" type="button" aria-label="关闭详情" @click="closeDrawer"><X :size="15" /></button>
      </header>
      <div class="tabs">
        <button
          v-for="item in TABS"
          :key="item.key"
          type="button"
          :class="{ on: drawerTab === item.key }"
          @click="setTab(item.key)"
        >{{ item.label }}</button>
      </div>
      <div class="scroll">
        <!-- 概览 -->
        <template v-if="drawerTab === 'summary'">
          <div class="stats">
            <div class="stat"><span>事件</span><b>{{ num(selectedRoom.eventCount) }}</b></div>
            <div class="stat"><span>玩家消息</span><b>{{ num(selectedRoom.messageCount) }}</b></div>
            <div class="stat"><span>搜证动作</span><b>{{ num(selectedRoom.investigationCount) }}</b></div>
            <div class="stat"><span>线索发放</span><b>{{ num(selectedRoom.clueCount) }}</b></div>
          </div>
          <div class="sect">本局统计</div>
          <div class="kv"><span>AI 请求 / 工具调用</span><b>{{ selectedRoom.aiRequests }} / {{ selectedRoom.toolCalls }}</b></div>
          <div class="kv">
            <span>失败运行 / 工具错误</span>
            <b :style="{ color: selectedRoom.failedRuns + selectedRoom.toolFailed ? 'var(--warn)' : 'var(--ok)' }">
              {{ selectedRoom.failedRuns }} / {{ selectedRoom.toolFailed }}
            </b>
          </div>
          <div class="kv"><span>Token 合计</span><b>{{ num(selectedRoom.tokenTotal) }}</b></div>
          <div class="kv"><span>阶段变更次数</span><b>{{ num(selectedRoom.stageChangeCount) }}</b></div>

          <div class="sect">阶段进度</div>
          <div class="rowflex wrap">
            <template v-for="(stage, index) in STAGE_FLOW" :key="stage">
              <span
                class="pill"
                :class="{ playing: stage === selectedRoom.stageId, ok: STAGE_FLOW.indexOf(selectedRoom.stageId) > index }"
              >{{ stageCn(stage) }}</span>
              <span v-if="index < STAGE_FLOW.length - 1" style="color: var(--faint)">·</span>
            </template>
          </div>

          <div class="sect">投票分布</div>
          <div v-for="row in voteRows" :key="row.target" class="votebar">
            <span class="n">{{ nameOf(selectedRoom, row.target) }}</span>
            <div class="bar"><i :style="barStyle(row.votes, row.max)"></i></div>
            <span class="num">{{ row.votes }}</span>
          </div>
          <p v-if="!voteRows.length" class="muted-line">还没有人投票。</p>
          <p v-if="selectedRoom.voteTied" style="color: var(--warn); font-size: 12px">票数持平，需要主持人裁定。</p>

          <template v-if="selectedRoom.ending">
            <div class="sect">结局</div>
            <div class="kv"><span>{{ selectedRoom.ending.title || selectedRoom.ending.id }}</span><b>{{ selectedRoom.ending.totalVotes || selectedRoom.ending.total_votes }} 票</b></div>
          </template>
          <template v-if="selectedRoom.publicClueIds.length">
            <div class="sect">公开线索</div>
            <div class="rowflex wrap">
              <span v-for="clueId in selectedRoom.publicClueIds" :key="clueId" class="pill">{{ clueId }}</span>
            </div>
          </template>
        </template>

        <!-- 玩家 -->
        <template v-else-if="drawerTab === 'players'">
          <div v-if="!selectedRoom.players.length" class="empty"><b>这个房间还没有玩家</b></div>
          <template v-else>
            <div class="sect">行为汇总</div>
            <table>
              <thead>
                <tr>
                  <th class="no">玩家</th><th class="no">角色</th><th class="no">消息</th><th class="no">提问</th>
                  <th class="no">地点</th><th class="no">翻查</th><th class="no">线索</th><th class="no">投票</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="player in selectedRoom.players" :key="player.id">
                  <tr class="player-row" @click="togglePlayer(player.id)">
                    <td><b>{{ player.name }}</b><span v-if="player.isHost" class="pill">房主</span></td>
                    <td>{{ player.characterId || "—" }}</td>
                    <td class="num">{{ player.stats?.message_count ?? 0 }}</td>
                    <td class="num">{{ player.stats?.question_count ?? 0 }}</td>
                    <td class="num">{{ player.stats?.location_count ?? player.enteredLocations.length }}</td>
                    <td class="num">{{ player.stats?.inspection_count ?? player.inspectedObjects.length }}</td>
                    <td class="num">{{ player.clueIds.length }}</td>
                    <td>
                      <span v-if="player.stats?.has_voted" class="pill ok">{{ nameOf(selectedRoom, player.stats.vote).split(" · ")[0] }}</span>
                      <span v-else class="pill">未投</span>
                    </td>
                  </tr>
                  <tr v-if="openPlayerId === player.id">
                    <td colspan="8">
                      <div class="history">
                        <div class="sect" style="margin-top:0">该玩家完整行为</div>
                        <p v-if="!playerHistory(player.id)" class="muted-line">正在读取…</p>
                        <template v-else>
                          <p v-if="!playerHistory(player.id).events.length" class="muted-line">这个玩家还没有留下事件。</p>
                          <div v-for="event in [...playerHistory(player.id).events].reverse()" :key="event.id" class="ev">
                            <time>{{ shortTime(event.created_at) }}</time>
                            <span class="t">{{ event.event_type }}</span>
                            <p class="wrap-text">{{ eventText(event) }}</p>
                          </div>
                        </template>
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>

            <div class="sect">搜证足迹</div>
            <div v-for="player in selectedRoom.players" :key="`foot-${player.id}`" class="kv">
              <span>{{ player.name }} <small style="color: var(--faint)">{{ player.characterId || "" }}</small></span>
              <b>{{ player.enteredLocations.length }} 个地点 · {{ player.inspectedObjects.length }} 件物品 · {{ player.clueIds.length }} 条线索</b>
            </div>

            <div class="sect">最后发言</div>
            <div v-for="player in selectedRoom.players.filter((item) => item.lastMessage)" :key="`msg-${player.id}`" class="qa">
              <p class="q">{{ player.name }}</p>
              <p class="a">{{ player.lastMessage }}</p>
            </div>
            <p v-if="!selectedRoom.players.some((item) => item.lastMessage)" class="muted-line">玩家还没有发言。</p>
          </template>
        </template>

        <!-- 事件流 -->
        <template v-else-if="drawerTab === 'events'">
          <div class="rowflex wrap" style="margin-bottom: 12px">
            <button
              v-for="type in selectedEventTypes"
              :key="type"
              type="button"
              class="chip"
              :class="{ on: eventFilter === type }"
              @click="eventFilter = type"
            >{{ type === "all" ? `全部 ${selectedRoom.events.length}` : type }}</button>
          </div>
          <div v-for="event in selectedEvents" :key="event.id" class="ev">
            <time>{{ shortTime(event.created_at) }}</time>
            <span class="t">{{ event.event_type }}</span>
            <p class="wrap-text" :title="eventText(event)">{{ eventText(event) }}</p>
            <span class="pill">{{ event.actor_player_id ? String(event.actor_player_id).slice(0, 6) : "系统" }}</span>
          </div>
          <div v-if="!selectedEvents.length" class="empty"><b>还没有事件</b></div>
        </template>

        <!-- AI 审计 -->
        <template v-else-if="drawerTab === 'ai'">
          <div class="stats">
            <div class="stat"><span>请求</span><b>{{ selectedRoom.aiRequests }}</b></div>
            <div class="stat"><span>工具调用</span><b>{{ selectedRoom.toolCalls }}</b></div>
            <div class="stat"><span>线索投递</span><b>{{ num(selectedRoom.clueDelivery) }}</b></div>
            <div class="stat">
              <span>失败</span>
              <b :style="{ color: selectedRoom.failedRuns + selectedRoom.toolFailed ? 'var(--warn)' : 'inherit' }">
                {{ selectedRoom.failedRuns + selectedRoom.toolFailed }}
              </b>
            </div>
          </div>

          <div class="sect">工具状态</div>
          <div v-for="(value, key) in selectedRoom.toolStatusCounts" :key="key" class="kv"><span>{{ key }}</span><b>{{ value }}</b></div>
          <p v-if="!Object.keys(selectedRoom.toolStatusCounts).length" class="muted-line">本局还没有工具调用。</p>

          <div class="sect">运行记录</div>
          <div v-for="(run, index) in selectedRoom.runs" :key="`run-${index}`" class="qa">
            <div class="f">
              <span class="pill" :class="runPillClass(run.status)">{{ run.status }}</span>
              <small>
                {{ run.request_type || "" }} · {{ stageCn(run.stage_id) }} ·
                {{ run.elapsed_ms != null ? Math.round(run.elapsed_ms) + "ms" : "—" }} ·
                {{ num((run.input_tokens || 0) + (run.output_tokens || 0)) }} token · {{ fullTime(run.created_at) }}
              </small>
            </div>
            <p v-if="run.error_code" class="a" style="color: var(--warn)">错误码 {{ run.error_code }}</p>
          </div>
          <p v-if="!selectedRoom.runs.length" class="muted-line">无运行记录。</p>

          <div class="sect">问答审计</div>
          <div v-for="entry in auditOfSelected?.entries || []" :key="entry.id" class="qa">
            <p class="q">{{ entry.question || "（无提问文字）" }}</p>
            <p class="a">{{ entry.answer || "（无回答文字）" }}</p>
            <div class="f">
              <span class="pill">{{ entry.visibility === "public" ? "公开" : "仅本人" }}</span>
              <span v-if="entry.tool_used" class="pill" :class="toolPillClass(entry)">{{ entry.tool_name || "tool" }}</span>
              <small>{{ entry.player_name || "" }} · {{ fullTime(entry.created_at) }}</small>
            </div>
          </div>
          <p v-if="!auditOfSelected" class="muted-line">正在读取问答审计…</p>
          <p v-else-if="!auditOfSelected.entries.length" class="muted-line">该房间暂无问答审计条目。</p>
        </template>

        <!-- 互评 -->
        <template v-else>
          <div v-if="!peerRows.length" class="empty">
            <b>还没有人提交互评</b>
            <div style="margin-top: 4px">互评在投票阶段之后由玩家提交。</div>
          </div>
          <div v-for="row in peerRows" :key="row.voterId" class="kv">
            <span>{{ nameOf(selectedRoom, row.voterId) }}</span>
            <b>最佳发言 {{ nameOf(selectedRoom, row.bestSpeakerId) }} · 最佳推理 {{ nameOf(selectedRoom, row.bestReasonerId) }}</b>
          </div>
        </template>
      </div>
      <footer>
        <button class="primary" type="button" :disabled="actionBusy" @click="exportRoom"><Download :size="14" />导出 JSON</button>
        <button class="ghost" type="button" @click="copyRoomId"><Copy :size="14" />复制房间号</button>
        <div class="sp"></div>
        <span style="font-size: 11px; color: var(--faint)"><Users :size="12" /> {{ selectedRoom.players.length }} 名玩家在册</span>
        <button class="danger" type="button" :disabled="actionBusy" @click="removeRoom"><Trash2 :size="14" />删除房间</button>
      </footer>
    </section>

    <div class="toast" :class="{ on: !!toastText }">{{ toastText }}</div>
  </main>
</template>
