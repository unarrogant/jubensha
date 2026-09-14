<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  ArrowLeft,
  Bot,
  Check,
  Clock3,
  Copy,
  Crown,
  Play,
  RefreshCw,
  Share2,
  UserRound,
  Users,
  Wifi,
  WifiOff,
} from "@lucide/vue";
import AppHeader from "../components/AppHeader.vue";
import { getRoom, getRoomPlayers, startRoom } from "../services/api";
import { RoomWebSocket } from "../services/websocket";
import { useRoomStore } from "../stores/room";

const route = useRoute();
const router = useRouter();
const roomStore = useRoomStore();
const room = ref(null);
const players = ref([]);
const loading = ref(true);
const refreshing = ref(false);
const starting = ref(false);
const errorMessage = ref("");
const connectionState = ref("connecting");
const copied = ref(false);
let roomSocket = null;

const roomId = computed(() => String(route.params.roomId).toUpperCase());
const session = computed(() => roomStore.readSession(roomId.value));
const isHost = computed(() => session.value?.isHost === true);
const script = computed(() => roomStore.getScript(room.value?.script_id));
const canStart = computed(
  () => room.value?.player_count === room.value?.required_players,
);
const missingPlayers = computed(() =>
  room.value
    ? Math.max(0, room.value.required_players - room.value.player_count)
    : 0,
);
const playerSlots = computed(() => {
  if (!room.value) return [];
  return Array.from({ length: room.value.required_players }, (_, index) => ({
    position: index + 1,
    player: players.value[index] || null,
  }));
});

async function loadLobby({ quiet = false } = {}) {
  if (quiet) refreshing.value = true;
  errorMessage.value = "";

  try {
    const [roomData, playerData] = await Promise.all([
      getRoom(roomId.value),
      getRoomPlayers(roomId.value),
    ]);

    room.value = roomData;
    players.value = playerData;

    if (roomData.status === "playing") {
      await router.replace(`/room/${roomId.value}`);
    }
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

function connectRoom() {
  if (!session.value?.playerId) {
    connectionState.value = "offline";
    return;
  }

  roomSocket = new RoomWebSocket({
    roomId: roomId.value,
    playerId: session.value.playerId,
  });

  roomSocket.on("open", () => {
    connectionState.value = "online";
  });
  roomSocket.on("close", () => {
    connectionState.value = "reconnecting";
  });
  roomSocket.on("error", () => {
    connectionState.value = "reconnecting";
  });
  roomSocket.on("message", async (event) => {
    if (event.type === "LOBBY_UPDATED" || event.type === "GAME_STARTED") {
      room.value = event.room;
      players.value = event.players;
    }
    if (event.type === "GAME_STARTED") {
      await router.replace(`/room/${roomId.value}`);
    }
  });

  roomSocket.connect();
}

async function handleStart() {
  if (!session.value?.playerId || !canStart.value) return;

  starting.value = true;
  errorMessage.value = "";
  try {
    await startRoom(roomId.value, session.value.playerId);
    await router.replace(`/room/${roomId.value}`);
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    starting.value = false;
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = true;
    window.setTimeout(() => {
      copied.value = false;
    }, 1800);
  } catch {
    errorMessage.value = `请手动复制：${text}`;
  }
}

function copyRoomCode() {
  return copyText(roomId.value);
}

function copyInvite() {
  return copyText(`${window.location.origin}/?room=${roomId.value}`);
}

function getPlayerAvatarUrl(player) {
  return roomStore.getAssetUrl(script.value, player?.character_avatar);
}

onMounted(async () => {
  if (!roomStore.scripts.length) {
    try {
      await roomStore.loadScripts();
    } catch {
      // 即使剧本简介失败，房间状态仍可单独加载。
    }
  }

  await loadLobby();
  connectRoom();
});

onBeforeUnmount(() => {
  roomSocket?.close();
});
</script>

<template>
  <div class="app-shell">
    <AppHeader>
      <template #center>
        <button class="header-room-id" type="button" title="复制房间号" @click="copyRoomCode">
          <span>房间号</span><strong>{{ roomId }}</strong>
          <Check v-if="copied" :size="14" /><Copy v-else :size="14" />
        </button>
      </template>
      <template #actions>
        <span class="connection-pill" :class="connectionState">
          <Wifi v-if="connectionState === 'online'" :size="14" />
          <WifiOff v-else :size="14" />
          {{ connectionState === "online" ? "实时同步" : connectionState === "offline" ? "仅查看" : "正在重连" }}
        </span>
      </template>
    </AppHeader>

    <main class="lobby-main">
      <div v-if="loading" class="page-loader"><span></span><p>正在进入等待大厅</p></div>

      <section v-else-if="errorMessage && !room" class="fatal-state">
        <strong>!</strong><h1>无法进入这个房间</h1><p>{{ errorMessage }}</p>
        <RouterLink class="button button-primary" to="/"><ArrowLeft :size="16" />返回剧本大厅</RouterLink>
      </section>

      <template v-else-if="room">
        <RouterLink class="back-link" to="/"><ArrowLeft :size="14" />返回剧本大厅</RouterLink>

        <section class="lobby-brief">
          <div class="lobby-cover"><img v-if="script" :src="roomStore.getCoverUrl(script)" :alt="script.title" /></div>
          <div class="lobby-copy">
            <div class="status-line"><span class="status-badge"><i></i>等待玩家加入</span><span>v{{ room.script_version }}</span></div>
            <h1>{{ script?.title || room.script_id }}</h1>
            <p>{{ script?.summary || "玩家到齐后，房主即可开启本局。" }}</p>
            <div class="brief-meta">
              <span><Users :size="14" />{{ room.required_players }} 人本</span>
              <span><Clock3 :size="14" />约 {{ script?.estimated_minutes || "--" }} 分钟</span>
              <span><Bot :size="14" />AI 主持</span>
            </div>
          </div>
          <div class="seat-summary">
            <strong>{{ room.player_count }}<small>/{{ room.required_players }}</small></strong>
            <span>{{ canStart ? "玩家已全部就位" : `还差 ${missingPlayers} 位玩家` }}</span>
            <span class="capacity-track"><i :style="{ width: `${(room.player_count / room.required_players) * 100}%` }"></i></span>
          </div>
        </section>

        <div v-if="errorMessage" class="inline-alert wide-alert" role="alert">
          <span>{{ errorMessage }}</span><button type="button" @click="errorMessage = ''">关闭</button>
        </div>

        <div class="lobby-layout">
          <section class="seat-section">
            <header class="section-bar compact">
              <div><span class="overline">PLAYERS</span><h2>{{ room.player_count }} 位玩家已就位</h2></div>
              <button class="icon-text-button" type="button" :disabled="refreshing" @click="loadLobby({ quiet: true })">
                <RefreshCw :size="15" :class="{ spinning: refreshing }" />刷新
              </button>
            </header>

            <div class="seat-grid">
              <article
                v-for="slot in playerSlots"
                :key="slot.position"
                class="seat-item"
                :class="{ empty: !slot.player, self: slot.player?.name === session?.playerName }"
              >
                <span class="seat-avatar">
                  <img
                    v-if="getPlayerAvatarUrl(slot.player)"
                    :src="getPlayerAvatarUrl(slot.player)"
                    :alt="slot.player.character_name"
                  />
                  <template v-else>{{ slot.player ? slot.player.name.slice(0, 1) : slot.position }}</template>
                </span>
                <div>
                  <strong>
                    {{ slot.player?.name || "等待加入" }}
                    <small v-if="slot.player?.name === session?.playerName" class="self-label">你</small>
                  </strong>
                  <span v-if="slot.player?.character_name">饰演 {{ slot.player.character_name }}</span>
                  <span v-else>{{ slot.player ? "已进入房间" : "空席位" }}</span>
                </div>
                <Crown v-if="slot.player && slot.position === 1" class="host-crown" :size="16" aria-label="房主" />
                <Check v-else-if="slot.player" class="ready-check" :size="16" aria-label="已就位" />
              </article>
            </div>
          </section>

          <aside class="room-control-panel">
            <span class="overline">ROOM CONTROL</span>
            <h2>{{ isHost ? "准备开局" : "等待房主开局" }}</h2>

            <p v-if="session" class="identity-note">当前身份：<strong>{{ session.playerName }}</strong>{{ isHost ? " · 房主" : "" }}</p>
            <p v-else class="identity-note warning"><UserRound :size="16" />当前浏览器没有本房间的玩家身份。</p>

            <div class="invite-block">
              <span>邀请玩家加入</span><strong>{{ roomId }}</strong>
              <div class="invite-actions">
                <button type="button" @click="copyRoomCode"><Copy :size="13" />复制房间号</button>
                <button type="button" @click="copyInvite"><Share2 :size="13" />{{ copied ? "已复制" : "邀请链接" }}</button>
              </div>
            </div>

            <button v-if="isHost" class="button button-primary start-button" type="button" :disabled="!canStart || starting" @click="handleStart">
              <Play :size="17" fill="currentColor" />{{ starting ? "正在开局" : canStart ? "开始游戏" : `等待 ${missingPlayers} 人` }}
            </button>
            <p class="control-help">{{ canStart ? "人数符合要求，开局后自动分配角色。" : "人数必须与剧本要求完全一致才能开始。" }}</p>
          </aside>
        </div>
      </template>
    </main>
  </div>
</template>
