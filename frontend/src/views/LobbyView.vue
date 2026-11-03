<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowLeft, Check, Copy, Crown, Play, Share2 } from "@lucide/vue";
import HubHeader from "../components/HubHeader.vue";
import { exitRoom as requestExitRoom, getRoom, getRoomPlayers, startRoom } from "../services/api";
import { RoomWebSocket } from "../services/websocket";
import { useRoomStore } from "../stores/room";

const route = useRoute();
const router = useRouter();
const roomStore = useRoomStore();
const room = ref(null);
const players = ref([]);
const loading = ref(true);
const starting = ref(false);
const leaving = ref(false);
const errorMessage = ref("");
const connectionState = ref("connecting");
const copied = ref("");
let roomSocket = null;
let lobbySyncTimer = null;

const roomId = computed(() => String(route.params.roomId).toUpperCase());
const session = computed(() => roomStore.readSession(roomId.value));
const isHost = computed(() => session.value?.isHost === true);
const script = computed(() => roomStore.getScript(room.value?.script_id));
const themeVars = computed(() => roomStore.getThemeVars(script.value));
const canStart = computed(
  () => room.value?.player_count === room.value?.required_players,
);
const missingPlayers = computed(() =>
  room.value
    ? Math.max(0, room.value.required_players - room.value.player_count)
    : 0,
);
const inviteUrl = computed(() => `${window.location.origin}/?room=${roomId.value}`);
const filledCount = computed(() => players.value.length);
const seatTotal = computed(() => room.value?.required_players || 0);
const playerSlots = computed(() => {
  if (!room.value) return [];
  return Array.from({ length: room.value.required_players }, (_, index) => ({
    position: index + 1,
    player: players.value[index] || null,
  }));
});
const chips = computed(() => {
  if (!script.value || !room.value) return [];
  return [
    `${room.value.required_players} 人本`,
    `约 ${script.value.estimated_minutes} 分钟`,
    `AI 主持 · ${roomStore.getDmName(script.value)}`,
    roomStore.getScriptTypeLabel(script.value),
  ];
});

async function loadLobby({ quiet = false } = {}) {
  if (quiet && (loading.value || starting.value)) return;
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
    // Recover the latest player list after an initial connection or reconnect.
    void loadLobby({ quiet: true });
  });
  roomSocket.on("close", () => {
    connectionState.value = "reconnecting";
  });
  roomSocket.on("error", () => {
    connectionState.value = "reconnecting";
  });
  roomSocket.on("message", async (event) => {
    if (event.type === "LOBBY_UPDATED" || event.type === "GAME_STARTED") {
      if (event.room) room.value = { ...room.value, ...event.room };
      if (Array.isArray(event.players)) {
        players.value = event.players;
      } else {
        await loadLobby({ quiet: true });
      }
    }
    if (event.type === "GAME_STARTED") {
      await router.replace(`/room/${roomId.value}`);
    }
  });

  roomSocket.connect();
}

async function handleStart() {
  if (!session.value?.playerId || !canStart.value || starting.value) return;

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

async function handleLeave() {
  if (!session.value?.playerId || leaving.value) return;
  leaving.value = true;
  errorMessage.value = "";
  try {
    await requestExitRoom(roomId.value, session.value.playerId);
    roomSocket?.close();
    roomStore.clearSession();
    await router.replace("/");
  } catch (error) {
    errorMessage.value = error.message;
    leaving.value = false;
  }
}

async function copyText(text, key) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = key;
    window.setTimeout(() => {
      copied.value = "";
    }, 1800);
  } catch {
    errorMessage.value = `请手动复制：${text}`;
  }
}

function getPlayerAvatarUrl(player) {
  return roomStore.getAssetUrl(script.value, player?.character_avatar);
}

function avatarInitial(player, position) {
  const label = String(player?.character_name || player?.name || position).trim();
  return Array.from(label)[0] || "?";
}

const connectionLabel = computed(() => {
  if (connectionState.value === "online") return "实时同步中";
  if (connectionState.value === "offline") return "仅查看";
  return "正在重连";
});

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
  lobbySyncTimer = window.setInterval(() => {
    if (room.value?.status === "waiting") {
      void loadLobby({ quiet: true });
    }
  }, 2000);
});

onBeforeUnmount(() => {
  if (lobbySyncTimer) window.clearInterval(lobbySyncTimer);
  roomSocket?.close();
});
</script>

<template>
  <div class="hub" :style="themeVars">
    <div class="hub-inner">
      <HubHeader
        :title="errorMessage && !room ? '无法进入房间' : '等待大厅'"
        :subtitle="`ROOM ${roomId}`"
        compact
      >
        <template #actions>
          <span class="pill"><span class="dot" :style="connectionState === 'online' ? {} : { background: 'var(--warn)', boxShadow: '0 0 9px var(--warn)' }"></span>{{ connectionLabel }}</span>
        </template>
      </HubHeader>

      <main class="wrap">
        <div v-if="loading" class="loader"><i></i><span>正在进入等待大厅…</span></div>

        <section v-else-if="errorMessage && !room" class="empty" style="margin-top: 60px">
          <strong>无法进入这个房间</strong>
          <span>{{ errorMessage }}</span>
          <RouterLink class="btn-ghost" to="/"><ArrowLeft :size="14" /> 返回剧本大厅</RouterLink>
        </section>

        <template v-else-if="room">
          <RouterLink class="back-link" to="/"><ArrowLeft :size="14" />返回剧本大厅</RouterLink>

          <div v-if="errorMessage" class="alert" role="alert" style="margin-top: 14px">
            <span>{{ errorMessage }}</span>
            <button type="button" @click="errorMessage = ''">关闭</button>
          </div>

          <section class="banner">
            <div class="cover">
              <img v-if="script" :src="roomStore.getCoverUrl(script)" :alt="roomStore.getDisplayName(script)" />
            </div>
            <div>
              <span class="overline">Waiting for Players · 本局剧本</span>
              <h1>{{ roomStore.getDisplayName(script) || room.script_id }} <small>v{{ room.script_version }}</small></h1>
              <p>{{ roomStore.getDisplaySummary(script) || "玩家到齐后，房主即可开启本局。" }}</p>
              <div class="chips">
                <span v-for="chip in chips" :key="chip">{{ chip }}</span>
              </div>
            </div>
            <div class="count">
              <b>{{ filledCount }}<small>/{{ seatTotal }}</small></b>
              <p>{{ canStart ? "玩家已全部就位" : `还差 ${missingPlayers} 位玩家` }}</p>
              <div class="track">
                <i :style="{ width: `${seatTotal ? Math.min(100, (filledCount / seatTotal) * 100) : 0}%` }"></i>
              </div>
            </div>
          </section>

          <div class="lobby-grid">
            <section class="card">
              <div class="pane-hd" style="padding: 0 0 14px; border: 0">
                <b style="font-size: 17px">玩家席位</b>
                <span class="pill" style="font-size: 11px">{{ filledCount }} / {{ seatTotal }} 已就位</span>
              </div>
              <div class="seats">
                <article
                  v-for="slot in playerSlots"
                  :key="slot.position"
                  class="seat"
                  :class="{ empty: !slot.player }"
                >
                  <span class="ava">
                    <img
                      v-if="getPlayerAvatarUrl(slot.player)"
                      :src="getPlayerAvatarUrl(slot.player)"
                      :alt="slot.player.character_name || slot.player.name"
                    />
                    <template v-else>{{ avatarInitial(slot.player, slot.position) }}</template>
                  </span>
                  <div>
                    <b>
                      {{ slot.player?.name || "虚位以待" }}
                      <small v-if="slot.player && slot.player.name === session?.playerName" class="you">你</small>
                    </b>
                    <span v-if="slot.player?.character_name" class="role">饰演 {{ slot.player.character_name }}</span>
                    <span v-else>{{ slot.player ? "已进入房间" : "等待玩家入席" }}</span>
                  </div>
                  <Crown v-if="slot.player && slot.position === 1" class="crown" :size="16" aria-label="房主" />
                </article>
              </div>
            </section>

            <aside class="card">
              <span class="overline">Room Control</span>
              <h3>{{ isHost ? "准备开局" : "等待房主开局" }}</h3>

              <p v-if="session" class="note" style="margin-top: 0">
                当前身份：<b style="color: var(--acc-soft)">{{ session.playerName }}</b>{{ isHost ? " · 房主" : "" }}
              </p>
              <p v-else class="note" style="margin-top: 0; color: var(--warn)">
                当前浏览器没有本房间的玩家身份，只能查看席位。
              </p>

              <div class="codebox">
                <b>{{ roomId }}</b>
                <p>分享房间号或邀请链接</p>
              </div>

              <button
                v-if="isHost"
                class="btn-main"
                type="button"
                style="margin-top: 0"
                :disabled="!canStart || starting"
                @click="handleStart"
              >
                {{ starting ? "正在开局" : canStart ? "开始游戏" : `等待 ${missingPlayers} 位玩家` }}
              </button>

              <div class="copy-row">
                <button class="btn-ghost" type="button" @click="copyText(roomId, 'code')">
                  <Copy v-if="copied !== 'code'" :size="13" /><Check v-else :size="13" />
                  {{ copied === "code" ? "已复制" : "复制房间号" }}
                </button>
                <button class="btn-ghost" type="button" @click="copyText(inviteUrl, 'link')">
                  <Share2 :size="13" />{{ copied === "link" ? "已复制" : "邀请链接" }}
                </button>
              </div>

              <div class="gate" style="margin-top: 14px">
                {{ isHost
                  ? "人数须与剧本要求完全一致，开局后自动分配角色。"
                  : "房主正在等待其他玩家入席，人数到齐后会自动开始。" }}
              </div>
              <p class="note">
                {{ canStart
                  ? "人数符合要求，开局后自动分配角色。"
                  : "人数必须与剧本要求完全一致才能开始。" }}
              </p>
              <button class="btn-ghost" type="button" style="width: 100%; margin-top: 12px" :disabled="leaving" @click="handleLeave">
                {{ leaving ? "正在退出…" : isHost ? "退出并销毁房间" : "退出等待大厅" }}
              </button>
            </aside>
          </div>
        </template>
      </main>
    </div>
  </div>
</template>

<style scoped>
.seat .you { display: inline-block; vertical-align: middle; }
</style>
