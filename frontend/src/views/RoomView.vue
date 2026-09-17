<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  BookOpen,
  Bot,
  CheckCircle2,
  Clock3,
  FileKey2,
  KeyRound,
  LogOut,
  Mic,
  MicOff,
  Radio,
  Send,
  ShieldAlert,
  Users,
  Volume2,
  Wifi,
  WifiOff,
} from "@lucide/vue";
import AppHeader from "../components/AppHeader.vue";
import {
  getGameState,
  getMessages,
  getMyCharacter,
  getMyClues,
  getRoom,
  getRoomPlayers,
  getVoteStatus,
  castVote,
  exitRoom as requestExitRoom,
} from "../services/api";
import { RoomWebSocket } from "../services/websocket";
import { WebRTCVoiceClient } from "../services/webrtc";
import { useRoomStore } from "../stores/room";

const route = useRoute();
const router = useRouter();
const roomStore = useRoomStore();
const room = ref(null);
const players = ref([]);
const character = ref(null);
const clues = ref([]);
const gameState = ref(null);
const messages = ref([]);
const messageText = ref("");
const loading = ref(true);
const sending = ref(false);
const awaitingHost = ref(false);
const stageAnnouncementPending = ref(false);
const errorMessage = ref("");
const connectionState = ref("connecting");
const activeCaseTab = ref("clues");
const remainingSeconds = ref(null);
const voteStatus = ref({
  has_voted: false,
  suspect_id: null,
  vote_count: 0,
  required_votes: 0,
  candidates: [],
});
const voteOpen = ref(false);
const selectedSuspectId = ref("");
const submittingVote = ref(false);
const voiceEnabled = ref(false);
const muted = ref(true);
const voiceState = ref("idle");
const voicePeers = ref({});
const messageList = ref(null);
const remoteAudioContainer = ref(null);
let roomSocket = null;
let voiceClient = null;
let clockTimer = null;
let stateSyncTimer = null;
let hasConnectedOnce = false;

const roomId = computed(() => String(route.params.roomId).toUpperCase());
const session = computed(() => roomStore.readSession(roomId.value));
const script = computed(() => roomStore.getScript(room.value?.script_id));
const stageName = computed(() => {
  const names = {
    intro: "角色自我介绍",
    investigation: "自由调查搜证",
    discussion: "集中讨论推理",
    voting: "投票指认",
    ending: "揭示真相",
  };
  return gameState.value?.stage_name
    || names[gameState.value?.stage_id]
    || "等待主持人";
});
const canExitRoom = computed(
  () => Boolean(room.value),
);
const formattedTime = computed(() => {
  if (remainingSeconds.value === null) return "--:--";
  const minutes = Math.floor(remainingSeconds.value / 60);
  const seconds = remainingSeconds.value % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
});
const myPublicPlayer = computed(() =>
  players.value.find((player) => player.name === session.value?.playerName),
);
const onlineVoiceCount = computed(() =>
  Object.values(voicePeers.value).filter(
    (peer) => peer.connectionState !== "offline",
  ).length + 1,
);
const characterAvatarUrl = computed(() =>
  roomStore.getAssetUrl(script.value, character.value?.avatar),
);
const hostAvatarUrl = computed(() =>
  roomStore.getAssetUrl(script.value, script.value?.agent_profile?.avatar),
);

function getPlayerAvatarUrl(player) {
  return roomStore.getAssetUrl(script.value, player?.character_avatar);
}

function getClueAssetUrl(clue) {
  const match = String(clue?.id || "").match(/(\d+)$/);
  return match ? `/img/clue${Number(match[1])}.jpg` : "";
}

function hideBrokenClueImage(event) {
  event.currentTarget.hidden = true;
}

function addMessage(message) {
  if (!message?.id || messages.value.some((item) => item.id === message.id)) return;
  messages.value.push(message);
  messages.value.sort((a, b) =>
    String(a.created_at || "").localeCompare(String(b.created_at || "")),
  );
  nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight;
  });
}

async function syncGameState() {
  try {
    const state = await getGameState(roomId.value);
    gameState.value = state;
    voteOpen.value = Boolean(state.vote_open);
    updateRemainingTime();
    if (state.stage_id === "voting" || state.stage_id === "ending") {
      await syncVoteStatus();
    }
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function syncVoteStatus() {
  if (!session.value?.playerId) return;
  try {
    const status = await getVoteStatus(roomId.value, session.value.playerId);
    voteStatus.value = status;
    if (status.suspect_id) selectedSuspectId.value = status.suspect_id;
  } catch (error) {
    // 投票尚未开始时接口会返回 400，页面无需显示错误。
    if (gameState.value?.stage_id === "voting" || gameState.value?.stage_id === "ending") {
      errorMessage.value = error.message;
    }
  }
}

async function submitVote() {
  if (
    !selectedSuspectId.value
    || voteStatus.value.has_voted
    || submittingVote.value
    || connectionState.value !== "online"
  ) return;

  submittingVote.value = true;
  errorMessage.value = "";
  try {
    const result = await castVote(
      roomId.value,
      session.value.playerId,
      selectedSuspectId.value,
    );
    voteStatus.value = {
      ...voteStatus.value,
      has_voted: true,
      suspect_id: selectedSuspectId.value,
      vote_count: result.vote_count,
      required_votes: result.required_votes,
    };
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    submittingVote.value = false;
  }
}

function updateRemainingTime() {
  const deadline = gameState.value?.stage_deadline;
  if (!deadline) {
    remainingSeconds.value = null;
    return;
  }

  remainingSeconds.value = Math.max(
    0,
    Math.ceil((new Date(deadline).getTime() - Date.now()) / 1000),
  );
}

async function loadGame() {
  if (!session.value?.playerId) {
    errorMessage.value = "当前浏览器没有这个房间的玩家身份，请先从剧本大厅加入。";
    loading.value = false;
    return;
  }

  try {
    if (!roomStore.scripts.length) await roomStore.loadScripts();

    const roomData = await getRoom(roomId.value);
    if (roomData.status === "waiting") {
      await router.replace(`/lobby/${roomId.value}`);
      return;
    }

    const [playerData, characterData, clueData, stateData, messageData] =
      await Promise.all([
        getRoomPlayers(roomId.value),
        getMyCharacter(roomId.value, session.value.playerId),
        getMyClues(roomId.value, session.value.playerId),
        getGameState(roomId.value),
        getMessages(roomId.value, session.value.playerId),
      ]);

    room.value = roomData;
    players.value = playerData;
    character.value = characterData;
    clues.value = clueData;
    gameState.value = stateData;
    voteOpen.value = Boolean(stateData.vote_open);
    updateRemainingTime();
    messages.value = messageData;
    stageAnnouncementPending.value = messageData.length === 0;
    if (stateData.stage_id === "voting" || stateData.stage_id === "ending") {
      await syncVoteStatus();
    }
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    loading.value = false;
  }
}

function attachRemoteStream(playerId, stream) {
  if (!remoteAudioContainer.value) return;
  let audio = remoteAudioContainer.value.querySelector(`[data-player-id="${playerId}"]`);
  if (!audio) {
    audio = document.createElement("audio");
    audio.autoplay = true;
    audio.dataset.playerId = playerId;
    remoteAudioContainer.value.appendChild(audio);
  }
  audio.srcObject = stream;
  audio.play().catch(() => {
    voiceState.value = "playback-blocked";
  });
}

function updateVoicePeer(playerId, changes) {
  if (!playerId) return;
  voicePeers.value = {
    ...voicePeers.value,
    [playerId]: {
      ...(voicePeers.value[playerId] || {}),
      id: playerId,
      ...changes,
    },
  };
}

function getPlayerVoiceStatus(playerName) {
  if (playerName === session.value?.playerName) {
    if (voiceState.value === "requesting") {
      return { label: "正在准备语音", tone: "connecting" };
    }
    if (!voiceEnabled.value) {
      return { label: "语音不可用", tone: "offline" };
    }
    return muted.value
      ? { label: "已静音", tone: "muted" }
      : { label: "麦克风开启", tone: "active" };
  }

  const peer = Object.values(voicePeers.value).find(
    (item) => item.name === playerName,
  );
  if (!peer || peer.connectionState === "offline") {
    return { label: "未连接语音", tone: "offline" };
  }
  return peer.muted
    ? { label: "已静音", tone: "muted" }
    : { label: "麦克风开启", tone: "active" };
}

function publishVoiceState() {
  roomSocket?.sendJson({
    type: "VOICE_STATE",
    muted: muted.value,
  });
}

async function connectRoom() {
  if (!session.value?.playerId) return;

  roomSocket = new RoomWebSocket({
    roomId: roomId.value,
    playerId: session.value.playerId,
  });

  muted.value = true;
  voiceState.value = "requesting";
  voiceClient = new WebRTCVoiceClient({
    websocket: roomSocket,
    playerId: session.value.playerId,
    onRemoteStream: attachRemoteStream,
    onPeerState: (playerId, state) => {
      updateVoicePeer(playerId, { connectionState: state });
      if (state === "connected") voiceState.value = "connected";
    },
  });

  roomSocket.on("open", () => {
    connectionState.value = "online";
    if (voiceEnabled.value) publishVoiceState();
    if (hasConnectedOnce) void syncGameState();
    hasConnectedOnce = true;
  });
  roomSocket.on("close", () => {
    connectionState.value = "reconnecting";
    awaitingHost.value = false;
  });
  roomSocket.on("error", () => {
    connectionState.value = "reconnecting";
  });
  roomSocket.on("message", async (event) => {
    if (event.type === "CHAT_HISTORY") {
      messages.value = event.messages || [];
      await nextTick();
      if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight;
    }
    if (["CHAT_MESSAGE", "PRIVATE_MESSAGE", "PUBLIC_MESSAGE"].includes(event.type)) {
      addMessage(event.message);
      if (event.type === "PRIVATE_MESSAGE" || event.type === "PUBLIC_MESSAGE") {
        awaitingHost.value = false;
      }
      if (event.type === "PUBLIC_MESSAGE") {
        stageAnnouncementPending.value = false;
        // 主持词可能先于阶段事件到达，重新从服务器读取状态，避免不同玩家状态不一致。
        await syncGameState();
        if (gameState.value?.stage_id === "voting" && gameState.value.vote_open) {
          voteOpen.value = true;
          activeCaseTab.value = "clues";
          await syncVoteStatus();
        }
      }
      if (event.message?.clue_ids?.length) {
        clues.value = await getMyClues(roomId.value, session.value.playerId);
      }
    }
    if (event.type === "ERROR") {
      awaitingHost.value = false;
      errorMessage.value = event.message || "请求处理失败，请稍后重试。";
    }
    if (event.type === "STAGE_CHANGED") {
      gameState.value = event.game;
      voteOpen.value = Boolean(event.game?.vote_open);
      stageAnnouncementPending.value = true;
      updateRemainingTime();
      if (event.game?.stage_id === "voting") {
        await syncVoteStatus();
      }
    }
    if (event.type === "VOTE_OPENED") {
      gameState.value = event.game || gameState.value;
      voteOpen.value = true;
      activeCaseTab.value = "clues";
      stageAnnouncementPending.value = false;
      await syncVoteStatus();
    }
    if (event.type === "VOTE_UPDATED") {
      voteStatus.value = {
        ...voteStatus.value,
        vote_count: event.vote_count ?? voteStatus.value.vote_count,
        required_votes: event.required_votes ?? voteStatus.value.required_votes,
      };
    }
    if (event.type === "GAME_ENDED") {
      room.value = { ...room.value, status: "ended" };
      gameState.value = event.game;
      stageAnnouncementPending.value = false;
      awaitingHost.value = false;
      updateRemainingTime();
    }
    if (event.type === "VOICE_PEERS") {
      for (const player of event.players || []) {
        updateVoicePeer(player.id, {
          name: player.name,
          muted: player.muted,
          connectionState: "online",
        });
      }
    } else if (event.type === "VOICE_PEER_JOINED") {
      updateVoicePeer(event.player_id, {
        name: event.player_name,
        muted: event.muted,
        connectionState: "online",
      });
    } else if (event.type === "VOICE_STATE_CHANGED") {
      updateVoicePeer(event.player_id, {
        name: event.player_name,
        muted: event.muted,
      });
    } else if (event.type === "VOICE_PEER_LEFT") {
      updateVoicePeer(event.player_id, {
        name: event.player_name,
        muted: true,
        connectionState: "offline",
      });
    }
    if (voiceClient) {
      try {
        await voiceClient.handleSignalMessage(event);
      } catch (error) {
        errorMessage.value = `语音连接失败：${error.message}`;
      }
    }
  });

  roomSocket.connect();
  try {
    await voiceClient.start({ muted: true });
    voiceEnabled.value = true;
    publishVoiceState();
    if (voiceState.value !== "connected") voiceState.value = "ready";
  } catch (error) {
    voiceEnabled.value = false;
    voiceState.value = "unavailable";
    errorMessage.value = `浏览器未能连接语音：${error.message}`;
  }
}

async function sendMessage() {
  const content = messageText.value.trim();
  if (!content || sending.value || connectionState.value !== "online") return;

  sending.value = true;
  errorMessage.value = "";
  const sent = roomSocket.sendJson({
    type: "PLAYER_PRIVATE_MESSAGE",
    content,
  });

  if (sent) messageText.value = "";
  else errorMessage.value = "连接尚未恢复，请稍后再试。";
  awaitingHost.value = sent;
  sending.value = false;
}

async function toggleMuted() {
  if (!voiceEnabled.value) {
    if (!voiceClient || voiceState.value === "requesting") return;

    errorMessage.value = "";
    voiceState.value = "requesting";
    try {
      await voiceClient.start({ muted: false });
      voiceEnabled.value = true;
      muted.value = false;
      voiceState.value = "ready";
      publishVoiceState();
    } catch (error) {
      voiceState.value = "unavailable";
      errorMessage.value = `浏览器未能连接语音：${error.message}`;
    }
    return;
  }

  muted.value = !muted.value;
  voiceClient?.setMuted(muted.value);
  publishVoiceState();

  if (!muted.value && remoteAudioContainer.value) {
    for (const audio of remoteAudioContainer.value.querySelectorAll("audio")) {
      audio.play().catch(() => {});
    }
  }
}

async function leaveRoom() {
  if (!session.value?.playerId || !canExitRoom.value) return;

  errorMessage.value = "";
  try {
    if (room.value?.status === "ended") {
      await requestExitRoom(roomId.value, session.value.playerId);
    }
    roomSocket?.close();
    voiceClient?.close();
    roomStore.clearSession();
    await router.replace("/");
  } catch (error) {
    errorMessage.value = error.message;
  }
}

function formatMessageTime(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

onMounted(async () => {
  await loadGame();
  if (!session.value?.playerId || !room.value) return;

  connectRoom();
  clockTimer = window.setInterval(() => {
    updateRemainingTime();
  }, 1000);
  // WebSocket 事件丢失或重连时，用服务器状态补偿同步；不会改变投票开放时机。
  stateSyncTimer = window.setInterval(() => {
    if (room.value?.status === "playing") {
      void syncGameState();
    }
  }, 2000);
});

onBeforeUnmount(() => {
  roomSocket?.close();
  voiceClient?.close();
  if (clockTimer) window.clearInterval(clockTimer);
  if (stateSyncTimer) window.clearInterval(stateSyncTimer);
});
</script>

<template>
  <div class="app-shell">
    <AppHeader>
      <template #center>
        <div class="game-stage-bar">
          <span>{{ stageName }}</span>
          <strong><Clock3 :size="16" />{{ formattedTime }}</strong>
        </div>
      </template>
      <template #actions>
        <div class="game-header-actions">
          <button
            class="voice-button"
            :class="{ active: voiceEnabled && !muted }"
            type="button"
            :disabled="voiceState === 'requesting'"
            :title="!voiceEnabled || muted ? '开启麦克风' : '关闭麦克风'"
            @click="toggleMuted"
          >
            <MicOff v-if="!voiceEnabled || muted" :size="14" /><Mic v-else :size="14" />
            {{ voiceState === "requesting" ? "连接语音中" : !voiceEnabled ? "开启麦克风" : muted ? "已静音" : "麦克风开启" }}
          </button>
          <button
            v-if="canExitRoom"
            class="exit-room-button"
            type="button"
            title="退出并返回剧本大厅"
            @click="leaveRoom"
          >
            <LogOut :size="14" />退出房间
          </button>
          <span class="connection-pill" :class="connectionState">
            <Wifi v-if="connectionState === 'online'" :size="14" /><WifiOff v-else :size="14" />
            {{ connectionState === "online" ? "已连接" : "重连中" }}
          </span>
        </div>
      </template>
    </AppHeader>

    <main v-if="loading" class="page-loader">
      <span></span><p>正在准备你的角色资料</p>
    </main>

    <main v-else-if="!room" class="fatal-state">
      <strong>!</strong><h1>无法进入游戏</h1>
      <p>{{ errorMessage }}</p>
      <RouterLink class="button button-primary" to="/">返回剧本大厅</RouterLink>
    </main>

    <main v-else class="game-main">
      <section class="game-command-bar">
        <div><span class="overline">ROOM</span><strong>{{ roomId }} · {{ script?.title || room.script_id }}</strong></div>
        <div class="stage-status"><Radio :size="15" /><span>当前阶段</span><strong>{{ stageName }}</strong></div>
        <span class="voice-summary"><Users :size="14" />{{ onlineVoiceCount }} 人在线</span>
      </section>

      <div v-if="errorMessage" class="inline-alert wide-alert">{{ errorMessage }}</div>

      <section class="game-workspace">
        <aside class="character-rail">
          <article class="character-sheet">
            <div class="character-portrait">
              <img v-if="characterAvatarUrl" :src="characterAvatarUrl" :alt="character?.name" />
              <span v-else>{{ character?.name?.slice(0, 1) || "?" }}</span>
            </div>
            <span class="overline">YOUR ROLE</span>
            <div class="player-identity">
              <span>玩家昵称</span>
              <strong>{{ session?.playerName || myPublicPlayer?.name || "未命名玩家" }}</strong>
            </div>
            <h1>{{ character?.name || myPublicPlayer?.character_name || "未分配" }}</h1>
            <p>{{ character?.public_profile || "暂无公开身份说明" }}</p>
            <span class="private-label"><KeyRound :size="13" />以下内容仅你可见</span>

            <section class="character-block">
              <h2>秘密背景</h2>
              <p>{{ character?.private_background || "暂无资料" }}</p>
            </section>
            <section class="character-block">
              <h2>个人目标</h2>
              <ul><li v-for="goal in character?.goals || []" :key="goal">{{ goal }}</li></ul>
            </section>
            <section class="character-block">
              <h2>秘密</h2>
              <ul><li v-for="secret in character?.secrets || []" :key="secret">{{ secret }}</li></ul>
            </section>
          </article>

          <section class="cast-list">
            <h2 class="rail-title"><Users :size="15" />公开角色表</h2>
            <div v-for="(player, index) in players" :key="`${player.name}-${index}`" class="cast-item">
              <span>
                <img
                  v-if="getPlayerAvatarUrl(player)"
                  :src="getPlayerAvatarUrl(player)"
                  :alt="player.character_name || player.name"
                />
                <template v-else>{{ player.name.slice(0, 1) }}</template>
              </span>
              <div>
                <strong>{{ player.name }}</strong>
                <small>{{ player.character_name || "角色未公开" }}</small>
                <small class="voice-presence" :class="getPlayerVoiceStatus(player.name).tone">
                  <i></i>{{ getPlayerVoiceStatus(player.name).label }}
                </small>
              </div>
            </div>
          </section>
        </aside>

        <section class="dm-console">
          <header class="console-header">
            <span class="dm-avatar">
              <img v-if="hostAvatarUrl" :src="hostAvatarUrl" alt="AI 主持人" />
              <Bot v-else :size="20" />
            </span>
            <div>
              <strong>{{ script?.agent_profile?.display_name || "AI 主持人" }}</strong>
              <span><i></i>正在主持 · {{ stageName }}</span>
            </div>
          </header>

          <div ref="messageList" class="message-list">
            <div v-if="stageAnnouncementPending" class="stage-transition-notice">
              <Radio :size="18" />
              <div>
                <strong>进入{{ stageName }}</strong>
                <span>{{ gameState?.stage_description || "阶段已经切换" }} 主持人正在宣布本阶段安排。</span>
              </div>
            </div>

            <div v-if="!messages.length && !stageAnnouncementPending" class="message-empty">
              <Bot :size="26" /><strong>主持人正在准备</strong><span>你可以私聊主持人询问角色信息或提交推理。</span>
            </div>

            <article
              v-for="message in messages"
              :key="message.id"
              class="message-item"
              :class="{
                player: message.type === 'PLAYER_PRIVATE_MESSAGE',
                public: message.channel === 'PUBLIC_MESSAGE',
              }"
              >
                <div class="message-meta">
                  <span>{{ message.type === "PLAYER_PRIVATE_MESSAGE" ? "你" : script?.agent_profile?.display_name || "主持人" }}</span>
                <small :class="message.channel === 'PUBLIC_MESSAGE' ? 'public-tag' : 'private-tag'">
                  {{ message.channel === "PUBLIC_MESSAGE" ? "公开信息" : "仅你可见" }}
                </small>
                </div>
                <p>{{ message.content }}</p>
                <div v-if="message.clue_ids?.length" class="message-clue-cards">
                  <img
                    v-for="clueId in message.clue_ids"
                    :key="`${message.id}-${clueId}`"
                    :src="getClueAssetUrl({ id: clueId })"
                    alt="线索卡"
                  />
                </div>
              </article>

            <div v-if="awaitingHost" class="dm-thinking" aria-label="主持人正在回复">
              主持人正在回应<span></span><span></span><span></span>
            </div>

            <section
              v-if="gameState?.stage_id === 'voting' && (voteOpen || gameState?.vote_open)"
              class="vote-panel vote-panel-chat"
            >
              <div class="vote-panel-heading">
                <div>
                  <span class="overline">FINAL ACCUSATION</span>
                  <h2>投票指认凶手</h2>
                </div>
                <ShieldAlert :size="18" />
              </div>
              <p class="vote-help">请选择一名角色作为你认为的凶手。每位玩家只能投票一次。</p>
              <div class="vote-options">
                <label
                  v-for="candidate in voteStatus.candidates"
                  :key="candidate.suspect_id"
                  class="vote-option"
                  :class="{ selected: selectedSuspectId === candidate.suspect_id }"
                >
                  <input
                    v-model="selectedSuspectId"
                    type="radio"
                    name="suspect"
                    :value="candidate.suspect_id"
                    :disabled="voteStatus.has_voted || submittingVote"
                  />
                  <span class="vote-option-avatar">
                    <img
                      v-if="roomStore.getAssetUrl(script, candidate.avatar)"
                      :src="roomStore.getAssetUrl(script, candidate.avatar)"
                      :alt="candidate.character_name || candidate.player_name"
                    />
                    <span v-else>{{ (candidate.character_name || candidate.player_name || '?').slice(0, 1) }}</span>
                  </span>
                  <span class="vote-option-copy">
                    <strong>{{ candidate.character_name || '未命名角色' }}</strong>
                    <small>{{ candidate.player_name || '未知玩家' }}</small>
                  </span>
                  <CheckCircle2 v-if="selectedSuspectId === candidate.suspect_id" :size="16" />
                </label>
              </div>
              <button
                class="vote-submit"
                type="button"
                :disabled="!selectedSuspectId || voteStatus.has_voted || submittingVote || connectionState !== 'online'"
                @click="submitVote"
              >
                {{ voteStatus.has_voted ? '已提交指认' : submittingVote ? '提交中…' : '确认指认' }}
              </button>
              <div class="vote-progress">
                <span>已投票 {{ voteStatus.vote_count }} / {{ voteStatus.required_votes }}</span>
                <span v-if="voteStatus.has_voted" class="vote-done">你的投票已记录</span>
              </div>
            </section>
          </div>

          <form class="message-composer" @submit.prevent="sendMessage">
            <KeyRound :size="16" />
            <label class="sr-only" for="host-message">私聊主持人</label>
            <textarea
              id="host-message"
              v-model="messageText"
              maxlength="1000"
              rows="2"
              placeholder="私聊主持人，询问、搜证或提交你的推理…"
              @keydown.enter.exact.prevent="sendMessage"
            ></textarea>
            <button type="submit" title="发送" :disabled="!messageText.trim() || connectionState !== 'online'">
              <Send :size="17" />
            </button>
          </form>
        </section>

        <aside class="case-rail">
          <div class="case-tabs" role="tablist" aria-label="线索与时间线">
            <button :class="{ active: activeCaseTab === 'clues' }" type="button" @click="activeCaseTab = 'clues'">
              <BookOpen :size="15" />线索 {{ clues.length }}
            </button>
            <button :class="{ active: activeCaseTab === 'timeline' }" type="button" @click="activeCaseTab = 'timeline'">
              <Clock3 :size="15" />时间线
            </button>
          </div>

          <div v-if="activeCaseTab === 'clues'" class="case-content">
            <header class="case-heading"><span class="overline">CASE FILE</span><h2>我的线索</h2></header>
            <article v-for="clue in clues" :key="clue.id" class="clue-item">
              <img
                v-if="getClueAssetUrl(clue)"
                class="clue-image"
                :src="getClueAssetUrl(clue)"
                :alt="clue.title"
                @error="hideBrokenClueImage"
              />
              <span>{{ clue.id.replace("clue_", "#") }}</span><h3>{{ clue.title }}</h3><p>{{ clue.content }}</p>
              <div><small v-for="tag in clue.tags" :key="tag">{{ tag }}</small></div>
            </article>
            <div v-if="!clues.length" class="case-empty"><BookOpen :size="25" /><span>获得的线索会出现在这里</span></div>
          </div>

          <div v-else class="case-content">
            <header class="case-heading"><span class="overline">PRIVATE TIMELINE</span><h2>我的时间线</h2></header>
            <ol class="timeline-list">
              <li v-for="item in character?.timeline || []" :key="`${item.time}-${item.description}`">
                <time>{{ item.time }}</time><p>{{ item.description }}</p>
              </li>
            </ol>
            <div v-if="!character?.timeline?.length" class="case-empty"><Clock3 :size="25" /><span>暂无时间线资料</span></div>
          </div>
        </aside>

        <div ref="remoteAudioContainer" hidden></div>
      </section>
    </main>
  </div>
</template>
