import { computed, ref } from "vue";
import { defineStore } from "pinia";
import {
  deleteAdminRoom,
  exportAdminRoom,
  getAdminAgentAudit,
  getAdminPlayerHistory,
  getAdminRoom,
  getAdminRoomSummary,
  getAdminRooms,
} from "../services/api";

const TOKEN_KEY = "script_kill_admin_token";

// 房间详情里带完整事件流，一次拉全部房间并不便宜；运营台只需要最近若干间的横向数据，
// 更早的房间在列表里仍可见，点开时再单独取。
const DETAIL_ROOM_LIMIT = 24;

function isAdminUnauthorized(error) {
  const message = String(error?.message || error);
  return message.includes("401") || message.includes("需要管理员登录") || message.includes("过期");
}

function percentile(sortedValues, ratio) {
  if (!sortedValues.length) return null;
  const index = Math.min(sortedValues.length - 1, Math.floor(sortedValues.length * ratio));
  return sortedValues[index];
}

function signatureOf(entry) {
  return [
    entry.status,
    entry.stage_id,
    entry.player_count,
    entry.script_version,
    entry.updated_at,
    entry.archived ? 1 : 0,
  ].join("|");
}

// 列表 / 汇总 / 原始快照三个接口说的是同一间房，这里压成一份运营台用的记录，
// 视图只读这份记录，不再各自去猜后端字段。
function normalizeRoom(entry, summary = {}, detail = {}) {
  const ai = summary.ai || {};
  const runs = ai.runs || detail.agent_runs || [];
  const latencies = runs
    .map((run) => Number(run.elapsed_ms))
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => left - right);
  const events = detail.event_history || [];
  const players = detail.players || [];
  const investigation = detail.investigation || {};
  const enteredByPlayer = investigation.entered_locations || {};
  const inspectedByPlayer = investigation.inspected_object_ids || {};
  const playerStats = summary.players || [];

  const lastMessageByPlayer = {};
  for (const event of events) {
    if (event.event_type !== "PLAYER_MESSAGE") continue;
    const content = event.payload?.content;
    if (event.actor_player_id && content) {
      lastMessageByPlayer[event.actor_player_id] = content;
    }
  }

  return {
    id: entry.id,
    scriptId: entry.script_id,
    scriptVersion: entry.script_version,
    status: entry.status,
    stageId: entry.stage_id,
    playerCount: entry.player_count || 0,
    requiredPlayers: entry.required_players || 0,
    createdAt: entry.created_at,
    updatedAt: entry.updated_at,
    endReason: entry.end_reason,
    archived: !!entry.archived,

    eventCount: summary.event_count ?? events.length,
    messageCount: summary.message_count ?? 0,
    publicMessageCount: summary.public_message_count ?? 0,
    clueCount: summary.clue_release_count ?? 0,
    investigationCount: summary.investigation_count ?? 0,
    stageChangeCount: summary.stage_change_count ?? 0,
    eventCounts: summary.event_counts || {},

    voteCount: summary.vote_count ?? 0,
    voteDistribution: summary.vote_distribution || {},
    voteLeaders: summary.vote_leaders || [],
    voteTied: !!summary.vote_tied,
    ending: summary.ending || null,

    aiRequests: ai.request_count ?? 0,
    toolCalls: ai.tool_call_count ?? 0,
    toolFailed: ai.failed_tool_count ?? 0,
    failedRuns: ai.failed_run_count ?? 0,
    runCount: ai.run_count ?? runs.length,
    clueDelivery: ai.clue_delivery_count ?? 0,
    toolStatusCounts: ai.tool_status_counts || {},
    failureCodes: ai.failure_codes || {},
    runtimeMetrics: ai.runtime_metrics || {},
    runs,
    tokenTotal: runs.reduce(
      (total, run) => total + (run.input_tokens || 0) + (run.output_tokens || 0),
      0,
    ),
    p50: percentile(latencies, 0.5),
    p95: percentile(latencies, 0.95),

    players: players.map((player) => ({
      id: player.id,
      name: player.name || player.id,
      isHost: !!player.is_host,
      characterId: player.character_id,
      clueIds: player.clue_ids || [],
      enteredLocations: enteredByPlayer[player.id] || [],
      inspectedObjects: inspectedByPlayer[player.id] || [],
      lastMessage: lastMessageByPlayer[player.id] || "",
      stats: playerStats.find((stat) => stat.player_id === player.id) || null,
    })),
    events,
    votes: detail.votes || {},
    peerReviews: detail.peer_reviews || {},
    publicClueIds: detail.public_clue_ids || [],
    summary,
  };
}

export const useAdminStore = defineStore("admin", () => {
  const rooms = ref([]);
  const loading = ref(false);
  const refreshing = ref(false);
  const error = ref("");
  const authFailed = ref(false);
  const snapshotAt = ref("");
  const selectedId = ref("");
  const audits = ref({});
  const histories = ref({});
  const detailFailedIds = ref([]);

  // 已抓过的房间先按签名缓存，轮询只重取真正变了的那几间。
  const signatures = new Map();

  const selectedRoom = computed(
    () => rooms.value.find((room) => room.id === selectedId.value) || null,
  );
  const loadedIds = computed(() => new Set(rooms.value.map((room) => room.id)));
  const scriptCount = computed(
    () => new Set(rooms.value.map((room) => room.scriptId).filter(Boolean)).size,
  );
  const runCount = computed(() => rooms.value.reduce((sum, room) => sum + room.runs.length, 0));

  function fail(error_) {
    if (isAdminUnauthorized(error_)) {
      authFailed.value = true;
      return;
    }
    error.value = error_?.message || "运营数据读取失败";
  }

  function select(roomId) {
    selectedId.value = roomId || "";
  }

  async function loadRooms() {
    const token = localStorage.getItem(TOKEN_KEY) || "";
    const list = await getAdminRooms(token);
    const changed = [];
    const dropped = [];

    for (const entry of list) {
      const next = signatureOf(entry);
      if (signatures.get(entry.id) !== next) {
        signatures.set(entry.id, next);
        changed.push(entry);
      }
    }
    for (const roomId of [...signatures.keys()]) {
      if (!list.some((entry) => entry.id === roomId)) {
        signatures.delete(roomId);
        dropped.push(roomId);
      }
    }
    return { list, changed, dropped, token };
  }

  async function fetchRoomPair(entry, token) {
    const [summary, detail] = await Promise.all([
      getAdminRoomSummary(entry.id, token).catch(() => ({})),
      getAdminRoom(entry.id, token).catch(() => null),
    ]);
    if (!detail) {
      // 详情拉不到就只展示列表与汇总，别让一间房拖垮整张表。
      if (!detailFailedIds.value.includes(entry.id)) detailFailedIds.value.push(entry.id);
    } else if (detailFailedIds.value.includes(entry.id)) {
      detailFailedIds.value = detailFailedIds.value.filter((id) => id !== entry.id);
    }
    return normalizeRoom(entry, summary, detail || {});
  }

  async function load({ force = false } = {}) {
    if (force) signatures.clear();
    loading.value = !rooms.value.length;
    refreshing.value = !!rooms.value.length;
    error.value = "";
    try {
      const { list, changed, dropped, token } = await loadRooms();
      const staleById = new Map(rooms.value.map((room) => [room.id, room]));
      const order = list.slice().sort((left, right) =>
        String(right.updated_at || right.created_at || "").localeCompare(
          String(left.updated_at || left.created_at || ""),
        ));
      const needDetail = new Set(
        order
          .filter((entry, index) => index < DETAIL_ROOM_LIMIT)
          .filter((entry) => changed.some((item) => item.id === entry.id))
          .map((entry) => entry.id),
      );
      if (selectedId.value) needDetail.add(selectedId.value);

      const detailed = await Promise.all(
        order
          .filter((entry) => needDetail.has(entry.id))
          .map((entry) => fetchRoomPair(entry, token)),
      );
      const detailedById = new Map(detailed.map((room) => [room.id, room]));

      rooms.value = order.map(
        (entry) =>
          detailedById.get(entry.id) ||
          (!force && staleById.get(entry.id)) ||
          normalizeRoom(entry, {}, {}),
      );
      for (const roomId of dropped) {
        delete audits.value[roomId];
        if (selectedId.value === roomId) selectedId.value = "";
      }
      snapshotAt.value = new Date().toISOString();
    } catch (error_) {
      fail(error_);
    } finally {
      loading.value = false;
      refreshing.value = false;
    }
  }

  async function loadAudit(roomId) {
    if (!roomId || audits.value[roomId]) return audits.value[roomId];
    try {
      const token = localStorage.getItem(TOKEN_KEY) || "";
      const payload = await getAdminAgentAudit(roomId, token);
      audits.value = { ...audits.value, [roomId]: payload };
      return payload;
    } catch (error_) {
      fail(error_);
      return { entries: [], peer_reviews: {} };
    }
  }

  async function loadPlayerHistory(roomId, playerId) {
    const key = `${roomId}:${playerId}`;
    if (histories.value[key]) return histories.value[key];
    try {
      const token = localStorage.getItem(TOKEN_KEY) || "";
      const payload = await getAdminPlayerHistory(roomId, playerId, token);
      histories.value = { ...histories.value, [key]: payload };
      return payload;
    } catch (error_) {
      fail(error_);
      return null;
    }
  }

  async function removeRoom(roomId) {
    const token = localStorage.getItem(TOKEN_KEY) || "";
    await deleteAdminRoom(roomId, token);
    signatures.delete(roomId);
    delete audits.value[roomId];
    if (selectedId.value === roomId) selectedId.value = "";
    await load({ force: true });
  }

  async function downloadExport(roomId) {
    const token = localStorage.getItem(TOKEN_KEY) || "";
    const blob = await exportAdminRoom(roomId, token);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `room-${roomId}-admin-export.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function auditEntries() {
    return [...loadedIds.value].flatMap((roomId) =>
      (audits.value[roomId]?.entries || []).map((entry) => ({ ...entry, roomId })),
    );
  }

  return {
    rooms, loading, refreshing, error, authFailed, snapshotAt,
    selectedId, selectedRoom, audits, histories, detailFailedIds,
    scriptCount, runCount,
    load, loadAudit, loadPlayerHistory, select,
    removeRoom, downloadExport, auditEntries,
  };
});
