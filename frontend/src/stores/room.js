import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { CONTENT_BASE_URL, createRoom, getScripts, getWaitingRooms, joinRoom } from "../services/api";

const SESSION_KEY = "script_game_tab_session";

export const useRoomStore = defineStore("room", () => {
  const scripts = ref([]);
  const waitingRooms = ref([]);
  const selectedScriptId = ref("");
  const catalogLoading = ref(false);
  const roomsLoading = ref(false);
  const selectedScript = computed(() =>
    scripts.value.find((script) => script.id === selectedScriptId.value),
  );

  async function loadScripts() {
    catalogLoading.value = true;
    try {
      scripts.value = await getScripts();
      if (!selectedScriptId.value) selectedScriptId.value = scripts.value[0]?.id || "";
    } finally {
      catalogLoading.value = false;
    }
  }

  async function loadWaitingRooms() {
    roomsLoading.value = true;
    try { waitingRooms.value = await getWaitingRooms(); }
    finally { roomsLoading.value = false; }
  }

  const selectScript = (scriptId) => { selectedScriptId.value = scriptId; };
  const getScript = (scriptId) =>
    scripts.value.find((script) => script.id === scriptId) || null;

  function getAssetUrl(script, relativePath) {
    if (!script || !relativePath) return "";
    const path = relativePath.split("/").map(encodeURIComponent).join("/");
    return `${CONTENT_BASE_URL}/${encodeURIComponent(script.id)}/v${script.version}/${path}`;
  }

  // 线索卡图片由前端 public/img 统一托管，不走剧本 content 目录。
  // clue_01、clue_1 都映射到 public/img/clue1.jpg。
  function getClueAssetUrl(clue) {
    const match = String(clue?.id || "").match(/clue[_-]?0*(\d+)/i);
    if (!match) return "";
    return `${new URL("/img/", CONTENT_BASE_URL).origin}/img/clue${Number(match[1])}.jpg`;
  }

  const getCoverUrl = (script) => getAssetUrl(script, script?.cover);

  const zh = (value, fallback) => value || fallback || "";

  // 整站配色跟随当前剧本：manifest.theme 缺省时沿用 hub.css 的默认金。
  function getThemeVars(script) {
    const theme = script?.theme;
    if (!theme) return {};
    return {
      "--acc": theme.acc,
      "--acc-soft": theme.soft,
      "--acc-dim": theme.dim,
      "--acc-line": theme.line,
      "--wash": theme.wash,
    };
  }

  const getDisplayName = (script) => zh(script?.title_zh, script?.title);
  const getDisplaySummary = (script) => zh(script?.summary_zh, script?.summary);
  const getDmName = (script) =>
    zh(script?.agent_profile?.display_name_zh, script?.agent_profile?.display_name) || "AI 主持人";

  const scriptTypeLabels = {
    murder_mystery: "本格推理",
    folklore_investigation: "民俗悬疑",
    psychological_mystery: "心理谜案",
  };
  const getScriptTypeLabel = (script) =>
    zh(script?.type_zh, scriptTypeLabels[script?.type]) || "沉浸剧本";

  // 大厅每张卡带自己的主题色；没有声明 theme 的剧本沿用默认金。
  function getScriptCardVars(script) {
    const theme = script?.theme || {};
    return {
      "--c": theme.acc || "var(--acc)",
      "--c-soft": theme.soft || "var(--acc-soft)",
    };
  }

  function saveSession(session) {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  }

  function readSession(roomId = null) {
    try {
      const session = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null");
      return roomId && session?.roomId !== roomId ? null : session;
    } catch { return null; }
  }

  function clearSession() {
    sessionStorage.removeItem(SESSION_KEY);
  }

  async function createNewRoom(hostName) {
    if (!selectedScript.value) throw new Error("请先选择剧本");
    const room = await createRoom({ scriptId: selectedScript.value.id, hostName });
    saveSession({ roomId: room.id, playerId: room.host_player_id, playerName: hostName, isHost: true });
    return room;
  }

  async function joinExistingRoom(roomId, playerName) {
    const normalizedRoomId = roomId.trim().toUpperCase();
    const player = await joinRoom(normalizedRoomId, playerName);
    saveSession({ roomId: normalizedRoomId, playerId: player.id, playerName: player.name, isHost: false });
    return { roomId: normalizedRoomId, player };
  }

  return {
    scripts, waitingRooms, selectedScriptId, selectedScript, catalogLoading, roomsLoading,
    loadScripts, loadWaitingRooms, selectScript, getScript, getAssetUrl, getClueAssetUrl, getCoverUrl,
    getThemeVars, getDisplayName, getDisplaySummary, getDmName, getScriptTypeLabel, getScriptCardVars,
    readSession, clearSession, createNewRoom, joinExistingRoom,
  };
});
