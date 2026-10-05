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
import AnnotatedText from "../components/AnnotatedText.vue";
import {
  getGameState,
  getMessages,
  getMyCharacter,
  getMyClues,
  getRoom,
  getRoomPlayers,
  getPeerReviewStatus,
  getVoteStatus,
  castVote,
  submitPeerReview,
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
const peerReview = ref({
  has_submitted: false,
  submitted_count: 0,
  required_count: 0,
  candidates: [],
  results_revealed: false,
  best_speakers: [],
  best_reasoners: [],
});
const selectedBestSpeakerId = ref("");
const selectedBestReasonerId = ref("");
const submittingPeerReview = ref(false);
const voiceEnabled = ref(false);
const muted = ref(true);
const voiceState = ref("idle");
const voicePeers = ref({});
const speakingPlayerIds = ref([]);
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
const stageOrder = {
  waiting: 0,
  role_selection: 1,
  intro: 2,
  investigation: 3,
  discussion: 4,
  voting: 5,
  ending: 6,
};
const stageName = computed(() => {
  const names = {
    intro: "Character Introductions",
    investigation: "Investigation",
    discussion: "Discussion and Deduction",
    voting: "最终投票",
    ending: "最终复盘",
  };
  return gameState.value?.stage_name
    || names[gameState.value?.stage_id]
    || "等待主持人";
});
const stageTasks = {
  intro: "请用角色身份介绍公开信息，不要透露角色卡上的秘密。你可以在对话框里向主持人提问。",
  investigation: "选择地点、检查物品，或提交你的推理。你可以在对话框里向主持人询问，符合条件的推理可能解锁证据。",
  discussion: "分享线索、质疑观点并整理最终推理。搜证已经结束，但仍可以向主持人提问或提交推理。",
  voting: "选择你认为最合理的最终答案，并完成一次投票。当前阶段不能继续搜证或提交新推理。",
  ending: "听主持人还原完整经过、公布投票结果，并说明每位角色的最终命运。",
};
const currentStageTask = computed(() =>
  stageTasks[gameState.value?.stage_id]
  || "Wait for the host to announce the next instruction.",
);
const englishPhraseNotes = ref([]);
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
const currentSpeakingPlayer = computed(() => {
  for (const playerId of [...speakingPlayerIds.value].reverse()) {
    const player = players.value.find((item) => item.id === playerId);
    if (player) return player;
  }
  return null;
});
const onlineVoiceCount = computed(() =>
  Object.values(voicePeers.value).filter(
    (peer) => peer.connectionState !== "offline",
  ).length + 1,
);
const characterAvatarUrl = computed(() =>
  roomStore.getAssetUrl(script.value, character.value?.avatar),
);
const characterVocabulary = computed(() => character.value?.vocabulary || []);
const hostAvatarUrl = computed(() =>
  roomStore.getAssetUrl(script.value, script.value?.agent_profile?.avatar),
);
const endingData = computed(() => gameState.value?.ending || null);
const endingVoteRows = computed(() => {
  const ending = endingData.value;
  if (!ending) return [];
  const names = Object.fromEntries(
    (ending.character_fate_list || []).map((item) => [item.character_id, item.character_name]),
  );
  return Object.entries(ending.vote_counts || {})
    .map(([characterId, count]) => ({
      characterId,
      characterName: names[characterId] || characterId,
      count,
    }))
    .sort((left, right) => right.count - left.count);
});
const endingTruth = computed(() => endingData.value?.truth_reveal || []);
const endingFates = computed(() => endingData.value?.character_fate_list || []);
const endingStory = computed(() => {
  const finalMessage = [...messages.value]
    .reverse()
    .find(
      (message) =>
        message.channel === "PUBLIC_MESSAGE" &&
        typeof message.content === "string" &&
        message.content.trim(),
    );

  return (
    finalMessage?.content ||
    endingData.value?.narrative ||
    "主持人正在准备本局最终真相。"
  );
});
const stageSpeechPrompts = {
  intro: "自我介绍阶段开始。请介绍公开身份，保留秘密，并在需要时向主持人提问。",
  investigation: "搜证阶段开始。请选择地点、检查物品，或向主持人提交推理。",
  discussion: "讨论阶段开始。请分享线索、质疑观点，并整理自己的推理。",
  voting: "最终投票阶段开始。请完成一次投票。",
  ending: "最终复盘开始。请听主持人还原经过并公布每位角色的命运。",
};
const spokenStageKeys = new Set();

function speakStagePrompt(state) {
  const stageId = state?.stage_id;
  const prompt = stageSpeechPrompts[stageId];
  if (!prompt || typeof window === "undefined" || !("speechSynthesis" in window)) return;

  const stageKey = `${roomId.value}:${stageId}:${state?.stage_started_at || ""}`;
  if (spokenStageKeys.has(stageKey)) return;

  try {
    if (window.sessionStorage.getItem(`stage-voice:${stageKey}`) === "1") return;
    window.sessionStorage.setItem(`stage-voice:${stageKey}`, "1");
  } catch {
    // 语音提示不是游戏状态，存储不可用时仍然允许本次播放。
  }

  spokenStageKeys.add(stageKey);
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(prompt);
  utterance.lang = "en-US";
  utterance.rate = 0.95;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
}

function getPlayerAvatarUrl(player) {
  return roomStore.getAssetUrl(script.value, player?.character_avatar);
}

function getRelationshipName(relationship) {
  if (relationship?.name || relationship?.character_name) {
    return relationship.name || relationship.character_name;
  }

  const knownNames = {
    macbeth: "Macbeth",
    lady_macbeth: "Lady Macbeth",
    banquo: "Banquo",
    malcolm: "Malcolm",
    macduff: "Macduff",
  };
  return knownNames[relationship?.target_id] || "Unknown character";
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
  updateStageAnnouncementPending();
}

function updateStageAnnouncementPending() {
  const stageStartedAt = gameState.value?.stage_started_at
    ? Date.parse(gameState.value.stage_started_at)
    : null;
  const hasCurrentStageAnnouncement = messages.value.some((message) => {
    if (message.channel !== "PUBLIC_MESSAGE") return false;
    if (!stageStartedAt || Number.isNaN(stageStartedAt)) return true;
    const createdAt = Date.parse(message.created_at || "");
    return Number.isNaN(createdAt) || createdAt >= stageStartedAt;
  });
  stageAnnouncementPending.value = !hasCurrentStageAnnouncement;
}

function applyGameState(nextState) {
  if (!nextState?.stage_id) return;

  const currentStageId = gameState.value?.stage_id;
  const nextStageId = nextState.stage_id;
  const currentOrder = stageOrder[currentStageId] ?? -1;
  const nextOrder = stageOrder[nextStageId] ?? -1;

  // 轮询请求可能比阶段事件更晚返回。不能让旧的 discussion/intro 状态
  // 覆盖已经进入 voting 的页面，否则投票面板会瞬间消失。
  if (
    currentStageId === "voting"
    && nextStageId !== "voting"
    && nextOrder < currentOrder
  ) {
    return;
  }

  if (currentStageId === "voting" && nextStageId === "voting") {
    // 投票一旦由 VOTE_OPENED 打开，在同一投票阶段不允许旧响应关闭它。
    const keepVoteOpen = voteOpen.value || Boolean(gameState.value?.vote_open);
    const nextVoteOpen = Boolean(nextState.vote_open) || keepVoteOpen;
    gameState.value = { ...nextState, vote_open: nextVoteOpen };
    voteOpen.value = nextVoteOpen;
    return;
  }

  gameState.value = nextState;
  voteOpen.value = Boolean(nextState.vote_open);
}

async function syncGameState() {
  try {
    const state = await getGameState(roomId.value);
    applyGameState(state);
    if (stageAnnouncementPending.value) {
      const history = await getMessages(roomId.value, session.value.playerId);
      messages.value = history;
    }
    updateStageAnnouncementPending();
    updateRemainingTime();
    if (state.stage_id === "voting" || state.stage_id === "ending") {
      await syncVoteStatus();
    }
    if (state.stage_id === "ending") await syncPeerReview();
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function syncPublicPlayers() {
  try {
    players.value = await getRoomPlayers(roomId.value);
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

async function syncPeerReview() {
  if (!session.value?.playerId || gameState.value?.stage_id !== "ending") return;
  try {
    const status = await getPeerReviewStatus(roomId.value, session.value.playerId);
    peerReview.value = status;
    selectedBestSpeakerId.value = status.best_speaker_id || selectedBestSpeakerId.value;
    selectedBestReasonerId.value = status.best_reasoner_id || selectedBestReasonerId.value;
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function submitPeerReviewVotes() {
  if (
    !selectedBestSpeakerId.value
    || !selectedBestReasonerId.value
    || peerReview.value.has_submitted
    || submittingPeerReview.value
  ) return;
  submittingPeerReview.value = true;
  errorMessage.value = "";
  try {
    await submitPeerReview(
      roomId.value,
      session.value.playerId,
      selectedBestSpeakerId.value,
      selectedBestReasonerId.value,
    );
    await syncPeerReview();
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    submittingPeerReview.value = false;
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
    errorMessage.value = "This browser has no player identity for the room. Please join from the lobby first.";
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
    applyGameState(stateData);
    speakStagePrompt(stateData);
    updateRemainingTime();
    messages.value = messageData;
    updateStageAnnouncementPending();
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

function updateSpeakingPlayer(playerId, speaking) {
  if (!playerId) return;
  if (speaking) {
    speakingPlayerIds.value = [
      ...speakingPlayerIds.value.filter((id) => id !== playerId),
      playerId,
    ];
    return;
  }
  speakingPlayerIds.value = speakingPlayerIds.value.filter((id) => id !== playerId);
}

function getPlayerVoiceStatus(player) {
  if (speakingPlayerIds.value.includes(player.id)) {
    return { label: "Speaking now", tone: "speaking" };
  }
  if (player.id === session.value?.playerId) {
    if (voiceState.value === "requesting") {
      return { label: "Preparing voice", tone: "connecting" };
    }
    if (!voiceEnabled.value) {
      return { label: "Voice unavailable", tone: "offline" };
    }
    return muted.value
      ? { label: "Muted", tone: "muted" }
      : { label: "Microphone on", tone: "active" };
  }

  const peer = Object.values(voicePeers.value).find(
    (item) => item.id === player.id,
  );
  if (!peer || peer.connectionState === "offline") {
    return { label: "Voice disconnected", tone: "offline" };
  }
  return peer.muted
    ? { label: "Muted", tone: "muted" }
    : { label: "Microphone on", tone: "active" };
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
    onSpeakingChange: updateSpeakingPlayer,
    onPeerState: (playerId, state) => {
      updateVoicePeer(playerId, { connectionState: state });
      if (state === "connected") voiceState.value = "connected";
    },
  });

  roomSocket.on("open", () => {
    connectionState.value = "online";
    void syncPublicPlayers();
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
    if (event.type === "LOBBY_UPDATED" || event.type === "GAME_STARTED") {
      if (event.room) room.value = { ...room.value, ...event.room };
      if (Array.isArray(event.players)) {
        players.value = event.players;
      } else {
        await syncPublicPlayers();
      }
      if (event.type === "GAME_STARTED" && event.game) {
        applyGameState(event.game);
        speakStagePrompt(event.game);
      }
    }
    if (event.type === "CHAT_HISTORY") {
      messages.value = event.messages || [];
      updateStageAnnouncementPending();
      await nextTick();
      if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight;
    }
    if (["CHAT_MESSAGE", "PRIVATE_MESSAGE", "PUBLIC_MESSAGE"].includes(event.type)) {
      addMessage(event.message);
      if (event.type === "PRIVATE_MESSAGE" || event.type === "PUBLIC_MESSAGE") {
        awaitingHost.value = false;
      }
      if (event.type === "PUBLIC_MESSAGE") {
        updateStageAnnouncementPending();
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
      errorMessage.value = event.message || "请求失败，请稍后再试。";
    }
    if (event.type === "STAGE_CHANGED") {
      applyGameState(event.game);
      speakStagePrompt(event.game);
      stageAnnouncementPending.value = true;
      updateRemainingTime();
      if (event.game?.stage_id === "voting") {
        await syncVoteStatus();
      }
    }
    if (event.type === "VOTE_OPENED") {
      applyGameState(event.game || gameState.value);
      voteOpen.value = true;
      if (gameState.value) gameState.value.vote_open = true;
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
    if (event.type === "PEER_REVIEW_UPDATED") {
      peerReview.value = {
        ...peerReview.value,
        submitted_count: event.submitted_count ?? peerReview.value.submitted_count,
        required_count: event.required_count ?? peerReview.value.required_count,
        results_revealed: event.results_revealed ?? peerReview.value.results_revealed,
      };
      await syncPeerReview();
    }
    if (event.type === "GAME_ENDED") {
      room.value = { ...room.value, status: "ended" };
      gameState.value = event.game;
      stageAnnouncementPending.value = false;
      awaitingHost.value = false;
      updateRemainingTime();
      await syncPeerReview();
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
      updateSpeakingPlayer(event.player_id, false);
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
        errorMessage.value = `Voice connection failed: ${error.message}`;
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
    errorMessage.value = `The browser could not connect to voice: ${error.message}`;
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
      errorMessage.value = `The browser could not connect to voice: ${error.message}`;
    }
    return;
  }

  muted.value = !muted.value;
  voiceClient?.setMuted(muted.value);
  void voiceClient?.resumeAudioAnalysis();
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
            :title="!voiceEnabled || muted ? 'Turn microphone on' : 'Mute microphone'"
            @click="toggleMuted"
          >
            <MicOff v-if="!voiceEnabled || muted" :size="14" /><Mic v-else :size="14" />
            {{ voiceState === "requesting" ? "Connecting voice" : !voiceEnabled ? "Enable microphone" : muted ? "Muted" : "Microphone on" }}
          </button>
          <button
            v-if="canExitRoom"
            class="exit-room-button"
            type="button"
            title="Leave the room and return to the lobby"
            @click="leaveRoom"
          >
            <LogOut :size="14" />Leave Room
          </button>
          <span class="connection-pill" :class="connectionState">
            <Wifi v-if="connectionState === 'online'" :size="14" /><WifiOff v-else :size="14" />
            {{ connectionState === "online" ? "Connected" : "Reconnecting" }}
          </span>
        </div>
      </template>
    </AppHeader>

    <main v-if="loading" class="page-loader">
      <span></span><p>Preparing your character dossier…</p>
    </main>

    <main v-else-if="!room" class="fatal-state">
      <strong>!</strong><h1>Unable to Enter the Game</h1>
      <p>{{ errorMessage }}</p>
      <RouterLink class="button button-primary" to="/">Return to the Lobby</RouterLink>
    </main>

    <main v-else class="game-main">
      <section class="game-command-bar">
        <div><span class="overline">ROOM</span><strong>{{ roomId }} · {{ script?.title || room.script_id }}</strong></div>
        <div class="stage-status"><Radio :size="15" /><span>CURRENT STAGE</span><strong>{{ stageName }}</strong></div>
        <span class="voice-summary"><Users :size="14" />{{ onlineVoiceCount }} online</span>
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
              <span>PLAYER NAME</span>
              <strong>{{ session?.playerName || myPublicPlayer?.name || "Unnamed Player" }}</strong>
            </div>
            <h1>{{ character?.name || myPublicPlayer?.character_name || "Unassigned" }}</h1>
            <p v-if="character?.tagline" class="character-tagline">{{ character.tagline }}</p>
            <span class="character-section-label">YOUR IDENTITY</span>
            <p>
              <AnnotatedText
                :text="character?.public_profile || 'No public profile available.'"
                :vocabulary="characterVocabulary"
              />
            </p>
            <span class="private-label"><KeyRound :size="13" />私信 — 只有你能看到</span>

            <section v-if="character?.case_background" class="character-block">
              <h2>案件信息</h2>
              <p>
                <AnnotatedText :text="character.case_background" :vocabulary="characterVocabulary" />
              </p>
            </section>
            <section v-if="character?.case_details?.length" class="character-block">
              <h2>Case Details</h2>
              <dl class="case-details-list">
                <div v-for="detail in character.case_details" :key="detail.label">
                  <dt>{{ detail.label }}</dt>
                  <dd><AnnotatedText :text="detail.value" :vocabulary="characterVocabulary" /></dd>
                </div>
              </dl>
            </section>
            <section v-if="character?.core_rules?.length" class="character-block">
              <h2>Core Rules</h2>
              <ul>
                <li v-for="rule in character.core_rules" :key="rule">{{ rule }}</li>
              </ul>
            </section>
            <section v-if="character?.private_background" class="character-block">
              <h2>Private Background</h2>
              <p>
                <AnnotatedText
                  :text="character?.private_background || 'No information available.'"
                  :vocabulary="characterVocabulary"
                />
              </p>
            </section>
            <section class="character-block">
              <h2>Public Goal</h2>
              <ul>
                <li v-for="goal in character?.goals || []" :key="goal">
                  <AnnotatedText :text="goal" :vocabulary="characterVocabulary" />
                </li>
              </ul>
            </section>
            <section class="character-block">
              <h2>Secret Missions</h2>
              <ul>
                <li v-for="secret in character?.secrets || []" :key="secret">
                  <AnnotatedText :text="secret" :vocabulary="characterVocabulary" />
                </li>
              </ul>
            </section>
            <section v-if="character?.story?.length" class="character-block">
              <h2>Your Story</h2>
              <ol class="character-story">
                <li v-for="paragraph in character.story" :key="paragraph">
                  <AnnotatedText :text="paragraph" :vocabulary="characterVocabulary" />
                </li>
              </ol>
            </section>
            <section v-if="character?.initial_information?.length" class="character-block">
              <h2>What You Know</h2>
              <ul>
                <li v-for="information in character.initial_information" :key="information">
                  <AnnotatedText :text="information" :vocabulary="characterVocabulary" />
                </li>
              </ul>
            </section>
            <section v-if="character?.relationships?.length" class="character-block">
              <h2>Relationships</h2>
              <ul>
                <li v-for="relationship in character.relationships" :key="relationship.character_id || relationship.name">
                  <strong>{{ getRelationshipName(relationship) }}</strong>
                  <span v-if="relationship.description"> — </span>
                  <AnnotatedText
                    v-if="relationship.description"
                    :text="relationship.description"
                    :vocabulary="characterVocabulary"
                  />
                </li>
              </ul>
            </section>
          </article>

          <section class="cast-list">
            <h2 class="rail-title"><Users :size="15" />Public Cast</h2>
            <div
              v-for="(player, index) in players"
              :key="`${player.name}-${index}`"
              class="cast-item"
              :class="{ speaking: speakingPlayerIds.includes(player.id) }"
            >
              <span class="cast-avatar">
                <img
                  v-if="getPlayerAvatarUrl(player)"
                  :src="getPlayerAvatarUrl(player)"
                  :alt="player.character_name || player.name"
                />
                <template v-else>{{ player.name.slice(0, 1) }}</template>
                <i v-if="speakingPlayerIds.includes(player.id)" class="cast-speaking-ring"></i>
              </span>
              <div>
                <strong>{{ player.name }} <em v-if="speakingPlayerIds.includes(player.id)" class="cast-speaking-badge"><Mic :size="11" />SPEAKING</em></strong>
                <small>{{ player.character_name || "Role not revealed" }}</small>
                <small class="voice-presence" :class="getPlayerVoiceStatus(player).tone">
                  <i></i>{{ getPlayerVoiceStatus(player).label }}
                </small>
              </div>
            </div>
          </section>
        </aside>

        <section class="dm-console">
          <header class="console-header meeting-console-header">
            <div class="meeting-host-card">
              <span class="dm-avatar">
                <img v-if="hostAvatarUrl" :src="hostAvatarUrl" alt="AI Host" />
                <Bot v-else :size="28" />
              </span>
              <div>
                <small>AI GAME HOST</small>
                <strong>{{ script?.agent_profile?.display_name || "AI Host" }}</strong>
                <span><i></i>HOSTING · {{ stageName }}</span>
              </div>
            </div>

            <div class="meeting-speaker-slot" :class="{ active: currentSpeakingPlayer }" aria-live="polite">
              <template v-if="currentSpeakingPlayer">
                <div class="meeting-speaker-portrait">
                  <img
                    v-if="getPlayerAvatarUrl(currentSpeakingPlayer)"
                    :src="getPlayerAvatarUrl(currentSpeakingPlayer)"
                    :alt="currentSpeakingPlayer.character_name || currentSpeakingPlayer.name"
                  />
                  <span v-else>{{ (currentSpeakingPlayer.character_name || currentSpeakingPlayer.name || "?").slice(0, 1) }}</span>
                </div>
                <div class="meeting-speaker-copy">
                  <span class="meeting-live-label"><Mic :size="13" />SPEAKING NOW</span>
                  <strong>{{ currentSpeakingPlayer.character_name || "Unrevealed Role" }}</strong>
                  <small>{{ currentSpeakingPlayer.name }}</small>
                </div>
              </template>
              <template v-else>
                <div class="meeting-speaker-empty-icon"><MicOff :size="23" /></div>
                <div class="meeting-speaker-copy">
                  <span class="meeting-live-label idle">CURRENT SPEAKER</span>
                  <strong>等待玩家发言</strong>
                  <small>正在发言的角色卡会显示在这里。</small>
                </div>
              </template>
            </div>
          </header>

          <section class="stage-mission" aria-live="polite">
            <span>NOW PLAYING</span>
            <h2>{{ stageName }}</h2>
            <p>{{ currentStageTask }}</p>
          </section>

          <div ref="messageList" class="message-list">
            <div v-if="stageAnnouncementPending" class="stage-transition-notice">
              <Radio :size="18" />
              <div>
                <strong>进入{{ stageName }}</strong>
                <span>{{ gameState?.stage_description || "阶段已经切换。" }} 主持人正在宣布本阶段安排。</span>
              </div>
            </div>

            <div v-if="!messages.length && !stageAnnouncementPending" class="message-empty">
              <Bot :size="26" /><strong>主持人正在准备。</strong><span>你可以询问角色信息，或向主持人提交推理。</span>
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
                  {{ message.channel === "PUBLIC_MESSAGE" ? "公开" : "私信" }}
                </small>
                </div>
                <p>{{ message.content }}</p>
                <div v-if="message.clue_ids?.length" class="message-clue-cards">
                  <img
                    v-for="clueId in message.clue_ids"
                    :key="`${message.id}-${clueId}`"
                    :src="getClueAssetUrl({ id: clueId })"
                    alt="Clue card"
                  />
                </div>
              </article>

            <div v-if="awaitingHost" class="dm-thinking" aria-label="主持人正在回复">
              主持人正在回复<span></span><span></span><span></span>
            </div>

            <section v-if="endingData" class="ending-panel" aria-live="polite">
              <div class="ending-panel-heading">
                <div>
                  <span class="overline">最终复盘</span>
                  <h2>真相与最终结局</h2>
                </div>
                <ShieldAlert :size="20" />
              </div>

              <section class="ending-section ending-vote-result">
                <span class="overline">1 · VOTE RESULT</span>
                <h3>最终选择</h3>
                <p v-if="endingData.suspect_name">本局票数最高的选择是 <strong>{{ endingData.suspect_name }}</strong>。</p>
                <p v-else>本次投票没有形成唯一的最高选择。</p>
                <div v-if="endingVoteRows.length" class="ending-vote-table">
                  <div v-for="row in endingVoteRows" :key="row.characterId" class="ending-vote-row">
                    <span>{{ row.characterName }}</span><strong>{{ row.count }} 票</strong>
                  </div>
                </div>
              </section>

              <section class="ending-section">
                <span class="overline">2 · 最终结局</span>
                <h3>{{ endingData.title || '最终结局' }}</h3>
                <p class="ending-narrative">{{ endingStory }}</p>
                <p v-if="endingData.winner_name" class="ending-winner">最终结果：<strong>{{ endingData.winner_name }}</strong></p>
              </section>

              <section class="ending-section">
                <span class="overline">3 · WHAT REALLY HAPPENED</span>
                <h3>事情究竟是怎样发生的</h3>
                <ol v-if="endingTruth.length" class="ending-truth-list">
                  <li v-for="truth in endingTruth" :key="truth">{{ truth }}</li>
                </ol>
                <p v-else>主持人暂时无法提供这次选择对应的真相还原。</p>
              </section>

              <section v-if="endingFates.length" class="ending-section">
                <span class="overline">4 · CASE REVIEW</span>
                <h3>每位角色最后的命运</h3>
                <div class="ending-fate-list">
                  <article v-for="fate in endingFates" :key="fate.character_id" class="ending-fate-item">
                    <strong>{{ fate.character_name }}</strong><p>{{ fate.fate }}</p>
                  </article>
                </div>
              </section>
            </section>

            <section v-if="endingData" class="peer-review-panel" aria-labelledby="peer-review-title">
              <div class="peer-review-heading">
                <div><span class="overline">PEER REVIEW</span><h2 id="peer-review-title">Recognize Your Fellow Players</h2></div>
                <Users :size="20" />
              </div>

              <template v-if="!peerReview.has_submitted">
                <p class="peer-review-help">每个奖项选择一名玩家。不能投给自己，提交后不能修改。</p>
                <div class="peer-review-fields">
                  <label>
                    <span>最佳发言者</span>
                    <small>发言积极、表达清晰、容易理解。</small>
                    <select v-model="selectedBestSpeakerId">
                      <option value="" disabled>请选择玩家</option>
                      <option v-for="candidate in peerReview.candidates" :key="`speaker-${candidate.player_id}`" :value="candidate.player_id">
                        {{ candidate.player_name }} · {{ candidate.character_name || '未知角色' }}
                      </option>
                    </select>
                  </label>
                  <label>
                    <span>最佳推理者</span>
                    <small>推理准确，能够充分使用线索。</small>
                    <select v-model="selectedBestReasonerId">
                      <option value="" disabled>请选择玩家</option>
                      <option v-for="candidate in peerReview.candidates" :key="`reasoner-${candidate.player_id}`" :value="candidate.player_id">
                        {{ candidate.player_name }} · {{ candidate.character_name || '未知角色' }}
                      </option>
                    </select>
                  </label>
                </div>
                <button
                  class="peer-review-submit"
                  type="button"
                  :disabled="!selectedBestSpeakerId || !selectedBestReasonerId || submittingPeerReview"
                  @click="submitPeerReviewVotes"
                >{{ submittingPeerReview ? '提交中…' : '提交互评' }}</button>
              </template>

              <div v-else-if="!peerReview.results_revealed" class="peer-review-waiting">
                <CheckCircle2 :size="20" />
                <div><strong>你的互评已记录。</strong><span>等待其他玩家完成：{{ peerReview.submitted_count }} / {{ peerReview.required_count }}</span></div>
              </div>

              <div v-else class="peer-review-results">
                <article>
                  <span>最佳发言者</span>
                  <h3>{{ peerReview.best_speakers.map((item) => item.player_name).join(' & ') }}</h3>
                  <p>{{ peerReview.best_speakers.map((item) => `${item.votes} 票`).join('、') }}</p>
                </article>
                <article>
                  <span>最佳推理者</span>
                  <h3>{{ peerReview.best_reasoners.map((item) => item.player_name).join(' & ') }}</h3>
                  <p>{{ peerReview.best_reasoners.map((item) => `${item.votes} 票`).join('、') }}</p>
                </article>
              </div>
            </section>

            <section
              v-if="gameState?.stage_id === 'voting' && (voteOpen || gameState?.vote_open)"
              class="vote-panel vote-panel-chat"
            >
              <div class="vote-panel-heading">
                <div>
                  <span class="overline">最终投票</span>
                  <h2>选择你的最终判断</h2>
                </div>
                <ShieldAlert :size="18" />
              </div>
              <p class="vote-help">请选择你认为最合理的最终答案。每名玩家只能投票一次。</p>
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
                {{ voteStatus.has_voted ? '已提交投票' : submittingVote ? '提交中…' : '确认投票' }}
              </button>
              <div class="vote-progress">
                <span>投票 {{ voteStatus.vote_count }} / {{ voteStatus.required_votes }}</span>
                <span v-if="voteStatus.has_voted" class="vote-done">你的投票已记录。</span>
              </div>
            </section>
          </div>

          <form class="message-composer" @submit.prevent="sendMessage">
            <KeyRound :size="16" />
            <label class="sr-only" for="host-message">Private message to the host</label>
            <textarea
              id="host-message"
              v-model="messageText"
              maxlength="1000"
              rows="2"
              placeholder="输入你想对主持人说的话，询问线索或提交推理…"
              @keydown.enter.exact.prevent="sendMessage"
            ></textarea>
            <button type="submit" title="Send" :disabled="!messageText.trim() || connectionState !== 'online'">
              <Send :size="17" />
            </button>
          </form>
        </section>

        <aside class="case-rail">
          <div class="case-tabs" role="tablist" aria-label="Clues, timeline, and suggested phrases">
            <button
              :class="{ active: activeCaseTab === 'clues' }"
              type="button"
              role="tab"
              :aria-selected="activeCaseTab === 'clues'"
              @click="activeCaseTab = 'clues'"
            >
              <BookOpen :size="15" />Clues {{ clues.length }}
            </button>
            <button
              :class="{ active: activeCaseTab === 'timeline' }"
              type="button"
              role="tab"
              :aria-selected="activeCaseTab === 'timeline'"
              @click="activeCaseTab = 'timeline'"
            >
              <Clock3 :size="15" />Timeline
            </button>
            <button
              :class="{ active: activeCaseTab === 'phrases' }"
              type="button"
              role="tab"
              :aria-selected="activeCaseTab === 'phrases'"
              @click="activeCaseTab = 'phrases'"
            >
              <FileKey2 :size="15" />Phrases
            </button>
          </div>

          <div v-if="activeCaseTab === 'clues'" class="case-content">
            <header class="case-heading"><span class="overline">CASE FILE</span><h2>My Clues</h2></header>
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
            <div v-if="!clues.length" class="case-empty"><BookOpen :size="25" /><span>Your discovered clues will appear here.</span></div>
          </div>

          <div v-else-if="activeCaseTab === 'timeline'" class="case-content">
            <header class="case-heading"><span class="overline">私人时间线</span><h2>我的时间线</h2></header>
            <ol class="timeline-list">
              <li v-for="item in character?.timeline || []" :key="`${item.time}-${item.description}`">
                <time>{{ item.time }}</time>
                <p>
                  <span v-if="item.phase" class="timeline-phase">{{ item.phase }}</span>
                  <AnnotatedText :text="item.description" :vocabulary="characterVocabulary" />
                </p>
              </li>
            </ol>
            <div v-if="!character?.timeline?.length" class="case-empty"><Clock3 :size="25" /><span>No timeline information is available.</span></div>
          </div>

          <div v-else class="case-content speaking-notes-content">
            <header class="case-heading">
              <span class="overline">SPEAKING SUPPORT</span>
              <h2>建议句式</h2>
            </header>
            <ul v-if="englishPhraseNotes.length" class="english-phrase-list">
              <li v-for="note in englishPhraseNotes" :key="note">{{ note }}</li>
            </ul>
            <div v-else class="case-empty phrase-empty">
              <FileKey2 :size="25" />
              <span>适合当前阶段的建议句式会记录在这里。</span>
            </div>
          </div>
        </aside>

        <div ref="remoteAudioContainer" hidden></div>
      </section>
    </main>
  </div>
</template>
