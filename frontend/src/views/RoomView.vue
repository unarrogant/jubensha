<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { LogOut, Mic, MicOff, Send } from "@lucide/vue";
import HubHeader from "../components/HubHeader.vue";
import AnnotatedText from "../components/AnnotatedText.vue";
import {
  getGameState,
  getMessages,
  getMyCharacter,
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
import { useClueStore } from "../stores/clues";
import { useInvestigationStore } from "../stores/investigation";

const route = useRoute();
const router = useRouter();
const roomStore = useRoomStore();
const clueStore = useClueStore();
const investigationStore = useInvestigationStore();

const room = ref(null);
const players = ref([]);
const character = ref(null);
const gameState = ref(null);
const messages = ref([]);
const messageText = ref("");
const loading = ref(true);
const sending = ref(false);
const awaitingHost = ref(false);
const stageAnnouncementPending = ref(false);
const errorMessage = ref("");
const connectionState = ref("connecting");
const activeRailTab = ref("clues");
const remainingSeconds = ref(null);
const pendingAction = ref(null);
const wsToast = ref({ text: "", clueId: "", on: false });
const expandedClueIds = ref([]);
const openedClue = ref(null);
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
const composerInput = ref(null);
const remoteAudioContainer = ref(null);
let roomSocket = null;
let voiceClient = null;
let clockTimer = null;
let stateSyncTimer = null;
let toastTimer = null;
let hasConnectedOnce = false;

const roomId = computed(() => String(route.params.roomId).toUpperCase());
const session = computed(() => roomStore.readSession(roomId.value));
const playerId = computed(() => session.value?.playerId || "");
const script = computed(() => roomStore.getScript(room.value?.script_id));
const themeVars = computed(() => roomStore.getThemeVars(script.value));
const stageOrder = {
  waiting: 0,
  role_selection: 1,
  intro: 2,
  investigation: 3,
  discussion: 4,
  voting: 5,
  ending: 6,
};
const stageNames = {
  waiting: "等待入席",
  role_selection: "角色分配",
  intro: "自我介绍",
  investigation: "搜证 · Investigation",
  discussion: "讨论推理",
  voting: "最终投票",
  ending: "最终复盘",
};
const stageName = computed(() => stageNames[gameState.value?.stage_id] || "等待主持人");
const stageTasks = {
  intro: "请用角色身份介绍公开信息，不要透露角色卡上的秘密。你也可以在对话框里向主持人提问。",
  investigation: "先点地点，再点物品。点击只会把中文句子填进输入框，发送后才会交给后端与 AI 主持人判定。",
  discussion: "分享线索、质疑观点并整理最终推理。搜证已经结束，但仍可以向主持人提问或提交推理。",
  voting: "选择你认为最合理的最终答案，并完成一次投票。当前阶段不能继续搜证。",
  ending: "听主持人还原完整经过、公布投票结果，并说明每位角色的最终命运。",
};
const currentStageTask = computed(() =>
  stageTasks[gameState.value?.stage_id] || "等待主持人宣布下一步安排。",
);
const canExitRoom = computed(() => Boolean(room.value));
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
  for (const id of [...speakingPlayerIds.value].reverse()) {
    const player = players.value.find((item) => item.id === id);
    if (player) return player;
  }
  return null;
});
const speakingPosition = computed(() => {
  if (!currentSpeakingPlayer.value) return 0;
  return players.value.findIndex(
    (player) => player.id === currentSpeakingPlayer.value.id,
  ) + 1;
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
const languageScaffold = computed(() => character.value?.language_scaffold || {});
const canInvestigate = computed(() => gameState.value?.stage_id === "investigation");
const connectionLabel = computed(() =>
  connectionState.value === "online"
    ? `已连接 · ${onlineVoiceCount.value} 人在线`
    : "正在重连",
);
const hostName = computed(() => roomStore.getDmName(script.value));
const scriptName = computed(() => roomStore.getDisplayName(script.value));
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
  waiting: "The room is waiting for players. Please wait until the cast is complete.",
  role_selection: "Role assignment has begun. Check your character information and wait for the host to start.",
  intro: "The introduction phase has begun. Introduce your public identity, keep your secrets private, and ask the host questions when needed.",
  investigation: "The investigation phase has begun. Search locations, inspect objects, or submit a deduction to the host.",
  discussion: "The discussion phase has begun. Share evidence, challenge theories, and organize your deductions.",
  voting: "The final voting phase has begun. Please cast your vote.",
  ending: "The final review has begun. Listen as the host reconstructs the case and reveals every character's fate.",
};
const spokenStageKeys = new Set();
let pendingStageSpeech = null;

function hasSpokenStage(stageKey) {
  if (spokenStageKeys.has(stageKey)) return true;
  try {
    return window.sessionStorage.getItem(`stage-voice:${stageKey}`) === "1";
  } catch {
    return false;
  }
}

function rememberSpokenStage(stageKey) {
  spokenStageKeys.add(stageKey);
  try {
    window.sessionStorage.setItem(`stage-voice:${stageKey}`, "1");
  } catch {
    // 语音记录不是游戏状态，存储不可用时不影响游戏流程。
  }
}

function playPendingStageSpeech() {
  const pending = pendingStageSpeech;
  if (!pending || typeof window === "undefined" || !("speechSynthesis" in window)) return;

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(pending.prompt);
  utterance.lang = "en-US";
  utterance.rate = 0.95;
  utterance.pitch = 1;
  utterance.onstart = () => {
    rememberSpokenStage(pending.stageKey);
    if (pendingStageSpeech?.stageKey === pending.stageKey) {
      pendingStageSpeech = null;
    }
  };
  utterance.onerror = () => {
    // 浏览器未获得用户手势时保留待播报内容，下一次点击页面会重试。
    pendingStageSpeech = pending;
  };
  window.speechSynthesis.speak(utterance);
}

function speakStagePrompt(state) {
  const stageId = state?.stage_id;
  const prompt = stageSpeechPrompts[stageId];
  if (!prompt || typeof window === "undefined" || !("speechSynthesis" in window)) return;

  const stageKey = `${roomId.value}:${stageId}:${state?.stage_started_at || ""}`;
  if (hasSpokenStage(stageKey)) return;
  if (pendingStageSpeech?.stageKey === stageKey) return;

  pendingStageSpeech = { stageKey, prompt };
  playPendingStageSpeech();
}

function retryPendingStageSpeech() {
  if (pendingStageSpeech) playPendingStageSpeech();
}

function resumeVoiceAudio() {
  void voiceClient?.resumeAudioAnalysis();
  if (remoteAudioContainer.value) {
    for (const audio of remoteAudioContainer.value.querySelectorAll("audio")) {
      audio.play().catch(() => {});
    }
  }
}

function getPlayerAvatarUrl(player) {
  return roomStore.getAssetUrl(script.value, player?.character_avatar);
}

// 没有角色图片的剧本也要保留角色视觉标识。
// 优先取角色名称首字，只有角色名称尚未公开时才回退到玩家昵称。
function getPlayerAvatarInitial(player) {
  const label = String(player?.character_name || player?.name || "?").trim();
  return Array.from(label)[0] || "?";
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
  return knownNames[relationship?.target_id] || "未知角色";
}

function flashToast(text, clueId = "") {
  wsToast.value = { text, clueId, on: true };
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    wsToast.value = { ...wsToast.value, on: false };
  }, 3400);
}

function getClueAssetUrl(clue) {
  return roomStore.getClueAssetUrl(clue);
}

function hideBrokenClueImage(event) {
  event.currentTarget.hidden = true;
}

function clueChipLabel(clueId) {
  const clue = clueStore.clueOf(clueId);
  if (clue) return `◆ ${clueStore.clueTitle(clue)} · ${clue.title}`;
  return `◆ 线索卡 ${String(clueId).replace("clue_", "#")}`;
}

function messageWho(message) {
  if (message.type === "PLAYER_PRIVATE_MESSAGE") return "你 · 私信主持人";
  if (message.channel === "PUBLIC_MESSAGE") return "主持人 · 公开";
  return "主持人 · 仅你可见";
}

function messageKind(message) {
  return message.type === "PLAYER_PRIVATE_MESSAGE" ? "me" : "dm";
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

// 搜证的句子由前端先补进聊天流，主持人的描述随后由 WebSocket 送达。
function addLocalPlayerMessage(content) {
  addMessage({
    id: `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    type: "PLAYER_PRIVATE_MESSAGE",
    channel: "PRIVATE_MESSAGE",
    content,
    created_at: new Date().toISOString(),
  });
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
      const history = await getMessages(roomId.value, playerId.value);
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

async function syncClues(revealedIds = []) {
  try {
    const added = await clueStore.refresh(roomId.value, playerId.value, revealedIds);
    if (!added.length) return;
    const first = clueStore.clueOf(added[0]);
    flashToast(
      first?.visibility === "public" ? "公开线索已同步全员" : "新线索只进你的墙",
      added.join("、"),
    );
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function syncVoteStatus() {
  if (!playerId.value) return;
  try {
    const status = await getVoteStatus(roomId.value, playerId.value);
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
  if (!playerId.value || gameState.value?.stage_id !== "ending") return;
  try {
    const status = await getPeerReviewStatus(roomId.value, playerId.value);
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
      playerId.value,
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
      playerId.value,
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
  if (!playerId.value) {
    errorMessage.value = "这个浏览器没有本房间的玩家身份，请先从大厅加入房间。";
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

    const [playerData, characterData, stateData, messageData] = await Promise.all([
      getRoomPlayers(roomId.value),
      getMyCharacter(roomId.value, playerId.value),
      getGameState(roomId.value),
      getMessages(roomId.value, playerId.value),
    ]);

    room.value = roomData;
    players.value = playerData;
    character.value = characterData;
    applyGameState(stateData);
    speakStagePrompt(stateData);
    updateRemainingTime();
    messages.value = messageData;
    updateStageAnnouncementPending();
    await clueStore.refresh(roomId.value, playerId.value);
    if (canInvestigate.value) {
      await investigationStore.loadLocations(roomId.value, playerId.value);
    }
    if (stateData.stage_id === "voting" || stateData.stage_id === "ending") {
      await syncVoteStatus();
    }
    if (stateData.stage_id === "ending") await syncPeerReview();
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
    return { label: "发言中", tone: "live" };
  }
  if (player.id === playerId.value) {
    if (!voiceEnabled.value) return { label: "语音未开", tone: "mute" };
    return muted.value
      ? { label: "已静音", tone: "mute" }
      : { label: "麦克风开启", tone: "live" };
  }

  const peer = Object.values(voicePeers.value).find((item) => item.id === player.id);
  if (!peer || peer.connectionState === "offline") {
    return { label: "语音离线", tone: "mute" };
  }
  return peer.muted
    ? { label: "已静音", tone: "mute" }
    : { label: "麦克风开启", tone: "live" };
}

function publishVoiceState() {
  roomSocket?.sendJson({
    type: "VOICE_STATE",
    muted: muted.value,
  });
}

async function connectRoom() {
  if (!playerId.value) return;

  roomSocket = new RoomWebSocket({
    roomId: roomId.value,
    playerId: playerId.value,
  });

  muted.value = true;
  voiceState.value = "requesting";
  voiceClient = new WebRTCVoiceClient({
    websocket: roomSocket,
    playerId: playerId.value,
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
    // Re-announce the current microphone state after every reconnect.
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
          await syncVoteStatus();
        }
      }
      if (event.message?.clue_ids?.length) {
        await syncClues(event.message.clue_ids);
      }
    }
    // 公开线索已经写进每个玩家的线索墙，这里只让客户端重新拉取。
    if (event.type === "CLUE_WALL_UPDATED") {
      await syncClues(event.clue_id ? [event.clue_id] : []);
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
      if (event.game?.stage_id === "investigation") {
        await investigationStore.loadLocations(roomId.value, playerId.value);
      }
      if (event.game?.stage_id === "voting") {
        await syncVoteStatus();
      }
    }
    if (event.type === "VOTE_OPENED") {
      applyGameState(event.game || gameState.value);
      voteOpen.value = true;
      if (gameState.value) gameState.value.vote_open = true;
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
    errorMessage.value = `浏览器无法连接语音：${error.message}`;
  }
}

function armSentence(sentence, action = null) {
  messageText.value = sentence;
  pendingAction.value = action;
  nextTick(() => composerInput.value?.focus());
}

function armEnterLocation(location) {
  if (!canInvestigate.value) return;
  armSentence(`我想进入${location.name_zh}看看。`, {
    kind: "enter",
    locationId: location.id,
  });
}

function armInspectObject(location, object) {
  if (!canInvestigate.value) return;
  armSentence(`我想检查${object.name_zh}。`, {
    kind: "inspect",
    locationId: location.id,
    objectId: object.id,
    objectName: object.name_zh,
  });
}

async function runArmedAction(action) {
  if (action.kind === "enter") {
    await investigationStore.enter(roomId.value, playerId.value, action.locationId);
    return;
  }
  await investigationStore.inspect(
    roomId.value,
    playerId.value,
    action.locationId,
    action.objectId,
    action.objectName,
  );
}

async function sendMessage() {
  const content = messageText.value.trim();
  if (!content || sending.value) return;

  const action = pendingAction.value;
  if (action) {
    sending.value = true;
    errorMessage.value = "";
    pendingAction.value = null;
    messageText.value = "";
    addLocalPlayerMessage(content);
    try {
      await runArmedAction(action);
    } catch (error) {
      errorMessage.value = error.message;
    } finally {
      sending.value = false;
    }
    return;
  }

  if (connectionState.value !== "online") {
    errorMessage.value = "连接尚未恢复，请稍后再试。";
    return;
  }

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
      errorMessage.value = `浏览器无法连接语音：${error.message}`;
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
  if (!playerId.value || !canExitRoom.value) return;

  errorMessage.value = "";
  try {
    if (room.value?.status === "waiting" || room.value?.status === "ended") {
      await requestExitRoom(roomId.value, playerId.value);
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

function toggleClueExpand(clueId) {
  expandedClueIds.value = expandedClueIds.value.includes(clueId)
    ? expandedClueIds.value.filter((id) => id !== clueId)
    : [...expandedClueIds.value, clueId];
}

function isClueClamped(clue) {
  return clueStore.clueBody(clue).length > 96 && !expandedClueIds.value.includes(clue.id);
}

function openClueViewer(clue) {
  openedClue.value = clue;
}

function closeClueViewer() {
  openedClue.value = null;
}

function handleEscape(event) {
  if (event.key === "Escape") closeClueViewer();
}

watch(
  () => gameState.value?.stage_id,
  async (stageId, previousStageId) => {
    if (stageId === "investigation" && previousStageId !== "investigation") {
      await investigationStore.loadLocations(roomId.value, playerId.value);
    }
  },
);

onMounted(async () => {
  window.addEventListener("pointerdown", retryPendingStageSpeech, { passive: true });
  window.addEventListener("pointerdown", resumeVoiceAudio, { passive: true });
  window.addEventListener("keydown", handleEscape);
  await loadGame();
  if (!playerId.value || !room.value) return;

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
  window.removeEventListener("pointerdown", retryPendingStageSpeech);
  window.removeEventListener("pointerdown", resumeVoiceAudio);
  window.removeEventListener("keydown", handleEscape);
  roomSocket?.close();
  voiceClient?.close();
  if (clockTimer) window.clearInterval(clockTimer);
  if (stateSyncTimer) window.clearInterval(stateSyncTimer);
  if (toastTimer) window.clearTimeout(toastTimer);
  investigationStore.reset();
  clueStore.reset();
});
</script>

<template>
  <div class="hub" :style="themeVars">
    <div class="hub-inner">
      <HubHeader
        compact
        :title="`${roomId} · ${scriptName}`"
        :subtitle="`ROOM ${roomId} · ${stageName}`"
      >
        <template #actions>
          <span class="pill"><span class="dot"></span>{{ connectionLabel }}</span>
        </template>
      </HubHeader>

      <div v-if="room" class="stagebar">
        <span>当前阶段 <b class="gold">{{ stageName }}</b></span>
        <span>剩余 <span class="clock">{{ formattedTime }}</span></span>
        <span>线索 <b class="gold">{{ clueStore.count }}</b> 条</span>
        <div class="right">
          <button class="btn-ghost" type="button" @click="toggleMuted">
            <MicOff v-if="!voiceEnabled || muted" :size="13" />
            <Mic v-else :size="13" />
            {{ !voiceEnabled ? "开启麦克风" : muted ? "已静音" : "麦克风开启" }}
          </button>
          <span class="pill">语音 · {{ onlineVoiceCount }} 人在场</span>
          <button v-if="canExitRoom" class="btn-ghost" type="button" @click="leaveRoom">
            <LogOut :size="13" />离开房间
          </button>
        </div>
      </div>

      <p v-if="errorMessage" class="alert" style="margin: 14px 26px 0">{{ errorMessage }}</p>

      <main v-if="loading" class="loader"><i></i></main>

      <main v-else-if="!room" class="card" style="margin: 22px 26px; padding: 26px">
        <p class="overline">无法进入房间</p>
        <h3 style="font-family: var(--serif); margin: 6px 0 12px">{{ errorMessage || "房间不存在" }}</h3>
        <RouterLink class="btn-main" style="display: inline-block" to="/">返回剧本大厅</RouterLink>
      </main>

      <main v-else class="game">
        <aside class="pane char">
          <div class="char-hero">
            <div class="ava">
              <img v-if="characterAvatarUrl" :src="characterAvatarUrl" :alt="character?.name" />
              <template v-else>{{ character?.name?.slice(0, 1) || "?" }}</template>
            </div>
            <h3>{{ character?.name || myPublicPlayer?.character_name || "尚未分配角色" }}</h3>
            <p>玩家 {{ session?.playerName || "匿名" }} · 你的角色</p>
          </div>

          <div class="blk">
            <h4>Public Identity · 公开身份</h4>
            <p>
              <AnnotatedText
                :text="character?.public_profile || '暂无公开身份。'"
                :vocabulary="characterVocabulary"
              />
            </p>
            <p v-if="character?.tagline" style="margin-top: 8px; color: var(--acc-soft)">
              {{ character.tagline }}
            </p>
          </div>

          <div v-if="character?.case_background" class="blk">
            <h4>Case · 案件信息</h4>
            <p><AnnotatedText :text="character.case_background" :vocabulary="characterVocabulary" /></p>
          </div>

          <div class="blk priv">
            <h4>Private · 仅你可见</h4>
            <ul>
              <li v-for="secret in character?.secrets || []" :key="secret">
                <AnnotatedText :text="secret" :vocabulary="characterVocabulary" />
              </li>
              <li v-for="information in character?.initial_information || []" :key="information">
                <AnnotatedText :text="information" :vocabulary="characterVocabulary" />
              </li>
            </ul>
            <p v-if="character?.private_background">
              <AnnotatedText :text="character.private_background" :vocabulary="characterVocabulary" />
            </p>
            <p
              v-if="!character?.secrets?.length && !character?.initial_information?.length && !character?.private_background"
            >角色卡没有额外私密内容。</p>
          </div>

          <div v-if="character?.goals?.length" class="blk">
            <h4>Goals · 目标</h4>
            <ul>
              <li v-for="goal in character.goals" :key="goal">
                <AnnotatedText :text="goal" :vocabulary="characterVocabulary" />
              </li>
            </ul>
          </div>

          <div v-if="character?.relationships?.length" class="blk">
            <h4>Relationships · 关系</h4>
            <ul>
              <li
                v-for="relationship in character.relationships"
                :key="relationship.character_id || relationship.name"
              >
                <strong style="color: var(--paper)">{{ getRelationshipName(relationship) }}</strong>
                <span v-if="relationship.description"> — </span>
                <AnnotatedText
                  v-if="relationship.description"
                  :text="relationship.description"
                  :vocabulary="characterVocabulary"
                />
              </li>
            </ul>
          </div>

          <div v-if="character?.story?.length" class="blk">
            <h4>Story · 你的经历</h4>
            <ul>
              <li v-for="paragraph in character.story" :key="paragraph">
                <AnnotatedText :text="paragraph" :vocabulary="characterVocabulary" />
              </li>
            </ul>
          </div>

          <div v-if="character?.core_rules?.length" class="blk">
            <h4>Rules · 本局规则</h4>
            <ul>
              <li v-for="rule in character.core_rules" :key="rule">{{ rule }}</li>
            </ul>
          </div>

          <div class="blk" style="padding: 0">
            <h4 style="padding: 13px 15px 0">Cast · 在场玩家</h4>
            <div
              v-for="(player, index) in players"
              :key="player.id || `${player.name}-${index}`"
              class="cast"
            >
              <span class="ava">
                <img
                  v-if="getPlayerAvatarUrl(player)"
                  :src="getPlayerAvatarUrl(player)"
                  :alt="player.character_name || player.name"
                />
                <template v-else>{{ getPlayerAvatarInitial(player) }}</template>
              </span>
              {{ player.name }} · {{ player.character_name || "角色未公开" }}
              <small class="say" :class="getPlayerVoiceStatus(player).tone">
                {{ getPlayerVoiceStatus(player).label }}
              </small>
            </div>
          </div>
        </aside>

        <section class="pane chat">
          <div class="dm-head">
            <div class="ava">
              <img v-if="hostAvatarUrl" :src="hostAvatarUrl" :alt="hostName" />
              <template v-else>幕</template>
            </div>
            <div style="flex: 1">
              <b>{{ hostName }}</b>
              <span>● 主持中 · {{ stageName }}</span>
            </div>
            <span class="pill" style="font-size: 10.5px">AI DM</span>
          </div>

          <div class="speak">
            <span class="dot" style="width: 7px; height: 7px"></span>
            当前发言者
            <b>{{ currentSpeakingPlayer
              ? `${currentSpeakingPlayer.name} · ${currentSpeakingPlayer.character_name || "角色未公开"}`
              : "等待玩家发言" }}</b>
            <span v-if="currentSpeakingPlayer" style="margin-left: auto; color: var(--faint)">
              第 {{ speakingPosition }} / {{ players.length }} 位
            </span>
          </div>

          <div class="mission"><b>{{ stageName }}</b>{{ currentStageTask }}</div>

          <div ref="messageList" class="msgs">
            <div v-if="stageAnnouncementPending" class="msg sys">
              <div class="who">STAGE</div>
              <div class="bub">进入{{ stageName }}。{{ gameState?.stage_description || "阶段已经切换。" }}主持人正在宣布本阶段安排。</div>
            </div>

            <div v-if="!messages.length && !stageAnnouncementPending" class="empty">
              <strong>主持人正在准备。</strong>
              <span>你可以询问角色信息，或向主持人提交推理。</span>
            </div>

            <article
              v-for="message in messages"
              :key="message.id"
              class="msg"
              :class="messageKind(message)"
            >
              <div class="who">{{ messageWho(message) }} · {{ formatMessageTime(message.created_at) }}</div>
              <div class="bub">{{ message.content }}<br v-if="message.clue_ids?.length" /><span
                v-for="clueId in message.clue_ids"
                :key="`${message.id}-${clueId}`"
                class="chip-clue"
              >{{ clueChipLabel(clueId) }}</span></div>
            </article>

            <div v-if="awaitingHost" class="thinking">主持人正在回复<i></i><i></i><i></i></div>

            <section
              v-if="gameState?.stage_id === 'voting' && (voteOpen || gameState?.vote_open)"
              class="panel"
            >
              <p class="overline" style="margin: 0">最终投票</p>
              <h3>选择你的最终判断</h3>
              <p class="help">请选择你认为最合理的最终答案。每名玩家只能投票一次。</p>
              <div class="opts">
                <label
                  v-for="candidate in voteStatus.candidates"
                  :key="candidate.suspect_id"
                  class="opt"
                  :class="{ sel: selectedSuspectId === candidate.suspect_id }"
                >
                  <input
                    v-model="selectedSuspectId"
                    type="radio"
                    name="suspect"
                    :value="candidate.suspect_id"
                    :disabled="voteStatus.has_voted || submittingVote"
                  />
                  <span class="ava">
                    <img
                      v-if="roomStore.getAssetUrl(script, candidate.avatar)"
                      :src="roomStore.getAssetUrl(script, candidate.avatar)"
                      :alt="candidate.character_name || candidate.player_name"
                    />
                    <template v-else>{{ (candidate.character_name || candidate.player_name || "?").slice(0, 1) }}</template>
                  </span>
                  <span class="who">
                    <b>{{ candidate.character_name || "未命名角色" }}</b>
                    <span>{{ candidate.player_name || "未知玩家" }}</span>
                  </span>
                </label>
              </div>
              <button
                class="btn-main"
                type="button"
                :disabled="!selectedSuspectId || voteStatus.has_voted || submittingVote || connectionState !== 'online'"
                @click="submitVote"
              >{{ voteStatus.has_voted ? "已提交投票" : submittingVote ? "提交中…" : "确认投票" }}</button>
              <div class="progress-row">
                <div class="track">
                  <i :style="{ width: `${Math.min(100, voteStatus.vote_count / Math.max(1, voteStatus.required_votes) * 100)}%` }"></i>
                </div>
                <span>{{ voteStatus.vote_count }} / {{ voteStatus.required_votes }}</span>
                <span v-if="voteStatus.has_voted">你的投票已记录。</span>
              </div>
            </section>

            <section v-if="endingData" class="panel">
              <p class="overline" style="margin: 0">最终复盘</p>
              <h3>真相与最终结局</h3>
              <div v-for="row in endingVoteRows" :key="row.characterId" class="row">
                <span>{{ row.characterName }}</span><b>{{ row.count }} 票</b>
              </div>
              <p v-if="endingData.suspect_name" class="help" style="margin-top: 10px">
                本局票数最高的选择是 {{ endingData.suspect_name }}。
              </p>
              <p class="help">{{ endingStory }}</p>
              <ol
                v-if="endingTruth.length"
                class="help"
                style="padding-left: 18px; margin: 8px 0"
              >
                <li v-for="truth in endingTruth" :key="truth">{{ truth }}</li>
              </ol>
              <div v-for="fate in endingFates" :key="fate.character_id" class="fate">
                <b>{{ fate.character_name }}</b>
                <p>{{ fate.fate }}</p>
              </div>
            </section>

            <section v-if="endingData" class="panel" style="margin-top: 12px">
              <p class="overline" style="margin: 0">Peer Review</p>
              <h3>给同场玩家一票</h3>
              <template v-if="!peerReview.has_submitted">
                <p class="help">每个奖项选择一名玩家。不能投给自己，提交后不能修改。</p>
                <div class="opts">
                  <label class="field" style="gap: 6px">
                    <span>最佳发言者</span>
                    <select v-model="selectedBestSpeakerId">
                      <option value="" disabled>请选择玩家</option>
                      <option
                        v-for="candidate in peerReview.candidates"
                        :key="`speaker-${candidate.player_id}`"
                        :value="candidate.player_id"
                      >{{ candidate.player_name }} · {{ candidate.character_name || "未知角色" }}</option>
                    </select>
                  </label>
                  <label class="field" style="gap: 6px">
                    <span>最佳推理者</span>
                    <select v-model="selectedBestReasonerId">
                      <option value="" disabled>请选择玩家</option>
                      <option
                        v-for="candidate in peerReview.candidates"
                        :key="`reasoner-${candidate.player_id}`"
                        :value="candidate.player_id"
                      >{{ candidate.player_name }} · {{ candidate.character_name || "未知角色" }}</option>
                    </select>
                  </label>
                </div>
                <button
                  class="btn-main"
                  type="button"
                  :disabled="!selectedBestSpeakerId || !selectedBestReasonerId || submittingPeerReview"
                  @click="submitPeerReviewVotes"
                >{{ submittingPeerReview ? "提交中…" : "提交互评" }}</button>
              </template>
              <p v-else-if="!peerReview.results_revealed" class="help">
                你的互评已记录，等待其他玩家完成：{{ peerReview.submitted_count }} / {{ peerReview.required_count }}
              </p>
              <div v-else>
                <div class="row">
                  <span>最佳发言者</span>
                  <b>{{ peerReview.best_speakers.map((item) => item.player_name).join(" & ") }}</b>
                </div>
                <div class="row">
                  <span>最佳推理者</span>
                  <b>{{ peerReview.best_reasoners.map((item) => item.player_name).join(" & ") }}</b>
                </div>
              </div>
            </section>
          </div>

          <div class="composer">
            <div class="filled">
              <textarea
                id="host-message"
                ref="composerInput"
                v-model="messageText"
                maxlength="1000"
                rows="2"
                placeholder="输入你想对主持人说的话…"
                @keydown.enter.exact.prevent="sendMessage"
              ></textarea>
              <button
                class="send"
                type="button"
                title="发送"
                :disabled="!messageText.trim() || sending"
                @click="sendMessage"
              ><Send :size="17" /></button>
            </div>
            <p class="tip">
              <template v-if="pendingAction">
                <b>● 中文已填入</b> · 发送后由后端按地点与物品执行，主持人的描述只回给你
              </template>
              <template v-else-if="messageText">
                <b>● 已填入输入框</b> · 可随意改动 · 按发送才交给后端与 AI 主持人
              </template>
              <template v-else>点地点或物品只会把句子填到这里，不发送也不请求后端；自由输入的句子交给 AI 主持人</template>
            </p>
          </div>
        </section>

        <aside class="pane rail">
          <div class="ws-toast" :class="{ on: wsToast.on }">
            {{ wsToast.text }}<b v-if="wsToast.clueId"> {{ wsToast.clueId }}</b>
          </div>

          <div class="seg">
            <button
              type="button"
              :class="{ on: activeRailTab === 'clues' }"
              @click="activeRailTab = 'clues'"
            >线索墙<small>{{ clueStore.count }}</small></button>
            <button
              type="button"
              :class="{ on: activeRailTab === 'timeline' }"
              @click="activeRailTab = 'timeline'"
            >时间线</button>
            <button
              type="button"
              :class="{ on: activeRailTab === 'search' }"
              @click="activeRailTab = 'search'"
            >搜证</button>
            <button
              type="button"
              :class="{ on: activeRailTab === 'speak' }"
              @click="activeRailTab = 'speak'"
            >表达</button>
          </div>

          <div class="rail-body">
            <div v-show="activeRailTab === 'clues'" class="tabpane">
              <p class="hint">公开线索同步全员，私密线索只进你自己的墙。缩略图保持线索卡原比例，点一下看整卡。</p>
              <div v-if="!clueStore.wall.length" class="empty">
                <strong>线索墙目前是空的。</strong>
                <span>它会随你的搜证与推理逐步长出来。</span>
              </div>
              <div
                v-for="clue in clueStore.wall"
                :key="clue.id"
                class="clue"
                :class="{ new: clueStore.newIds.includes(clue.id) }"
              >
                <button class="thumb" type="button" @click="openClueViewer(clue)">
                  <img
                    v-if="getClueAssetUrl(clue)"
                    :src="getClueAssetUrl(clue)"
                    :alt="`${clueStore.clueTitle(clue)}线索卡`"
                    @error="hideBrokenClueImage"
                  />
                </button>
                <div class="cc">
                  <div class="top">
                    <b>{{ clueStore.clueTitle(clue) }}</b>
                    <span class="vis" :class="clue.visibility === 'public' ? 'pub' : 'pri'">
                      {{ clue.visibility === "public" ? "公开" : "私密 · 仅你" }}
                    </span>
                  </div>
                  <small>{{ clue.title }} · {{ clue.id.replace("clue_", "#") }}</small>
                  <p :class="{ clamp: isClueClamped(clue) }">{{ clueStore.clueBody(clue) }}</p>
                  <button
                    v-if="clueStore.clueBody(clue).length > 96"
                    class="more"
                    type="button"
                    @click="toggleClueExpand(clue.id)"
                  >{{ expandedClueIds.includes(clue.id) ? "收起" : "展开全文" }}</button>
                </div>
              </div>
            </div>

            <div v-show="activeRailTab === 'timeline'" class="tabpane">
              <p class="hint">时间线来自角色卡，只按你的角色下发。</p>
              <ul v-if="character?.timeline?.length" class="tl">
                <li v-for="item in character.timeline" :key="`${item.time}-${item.description}`">
                  <time>{{ item.time }}</time>
                  <div>
                    <span v-if="item.phase" class="ph">{{ item.phase }}</span>
                    <AnnotatedText :text="item.description" :vocabulary="characterVocabulary" />
                  </div>
                </li>
              </ul>
              <div v-else class="empty">
                <strong>这个角色还没有时间线。</strong>
                <span>可以向主持人询问角色当夜的行踪。</span>
              </div>
            </div>

            <div v-show="activeRailTab === 'search'" class="tabpane">
              <p class="hint">
                {{ canInvestigate
                  ? "先点地点，再点物品。点击只会把中文句子填进输入框，不发送、也不请求后端。"
                  : "搜证只在搜证阶段开放；进入该阶段后这里会列出可以前往的地点。" }}
              </p>
              <div v-if="investigationStore.loading" class="empty">
                <strong>正在读取地点清单…</strong>
              </div>
              <div v-else-if="!investigationStore.locations.length" class="empty">
                <strong>{{ investigationStore.error || "暂时没有可以前往的地点。" }}</strong>
                <span>阶段切换后会自动重新载入。</span>
              </div>
              <div
                v-for="location in investigationStore.locations"
                :key="location.id"
                class="loc"
                :class="{
                  on: investigationStore.isEntered(location.id),
                  spent: investigationStore.isEntered(location.id)
                    && investigationStore.objectsOf(location.id).length > 0
                    && investigationStore.progressOf(location.id).done
                      === investigationStore.objectsOf(location.id).length,
                }"
              >
                <div class="lh">
                  <b>{{ location.name_zh }}</b>
                  <span
                    v-if="investigationStore.isEntered(location.id) && investigationStore.objectsOf(location.id).length"
                    class="prog"
                  >{{ investigationStore.progressOf(location.id).done }}/{{ investigationStore.objectsOf(location.id).length }}</span>
                  <span
                    v-else
                    class="tag"
                    :class="investigationStore.isEntered(location.id) ? 'done' : 'open'"
                  >{{ investigationStore.isEntered(location.id) ? "已进入" : "可进入" }}</span>
                </div>
                <p>{{ location.summary_zh }}</p>

                <div v-if="investigationStore.isEntered(location.id)">
                  <div v-if="investigationStore.objectsOf(location.id).length" class="objs">
                    <div
                      v-for="object in investigationStore.objectsOf(location.id)"
                      :key="object.id"
                      class="objrow"
                      :class="investigationStore.statusOf(object.id)"
                    >
                      <button
                        v-if="investigationStore.statusOf(object.id) === 'free'"
                        class="obj"
                        type="button"
                        :disabled="!canInvestigate"
                        @click="armInspectObject(location, object)"
                      >
                        <span class="st"></span>
                        <span class="nm">{{ object.name_zh }}</span>
                        <span class="mk">填入输入框</span>
                      </button>
                      <div v-else class="obj">
                        <span class="st"></span>
                        <span class="nm">{{ object.name_zh }}</span>
                        <span class="mk">{{ investigationStore.statusOf(object.id) === "mine" ? "已搜查" : "已被搜查" }}</span>
                      </div>
                      <p v-if="investigationStore.statusOf(object.id) === 'mine'" class="res">
                        {{ investigationStore.myResults[object.id] }}
                      </p>
                      <p v-else-if="investigationStore.statusOf(object.id) === 'gone'" class="res">
                        这里已经有人翻过一遍，主持人只把结果发给了搜查者。
                      </p>
                    </div>
                  </div>
                </div>
                <button
                  v-else
                  class="loc-act"
                  type="button"
                  :disabled="!canInvestigate"
                  @click="armEnterLocation(location)"
                >进入{{ location.name_zh }}</button>
              </div>
            </div>

            <div v-show="activeRailTab === 'speak'" class="tabpane">
              <p class="hint">表达脚手架为英语玩家提供句型与词汇，点句子直接填入输入框。</p>
              <template v-for="group in languageScaffold.sentence_patterns || []" :key="group.category">
                <div class="scaf-cat">{{ group.category }}</div>
                <button
                  v-for="item in group.items"
                  :key="item.pattern"
                  class="scaf"
                  type="button"
                  @click="armSentence(item.pattern)"
                >
                  <b>{{ item.pattern }}</b>
                  <span v-if="item.meaning">{{ item.meaning }}</span>
                </button>
              </template>
              <template v-for="group in languageScaffold.vocabulary || []" :key="`vocabulary-${group.category}`">
                <div class="scaf-cat">{{ group.category }} · 词汇</div>
                <button
                  v-for="item in group.items"
                  :key="item.term"
                  class="scaf"
                  type="button"
                  @click="armSentence(item.term)"
                >
                  <b>{{ item.term }}</b>
                  <span v-if="item.meaning">{{ item.meaning }}</span>
                </button>
              </template>
              <div
                v-if="!languageScaffold.sentence_patterns?.length && !languageScaffold.vocabulary?.length"
                class="empty"
              >
                <strong>这个剧本暂未整理表达脚手架。</strong>
              </div>
            </div>
          </div>
        </aside>

        <div ref="remoteAudioContainer" hidden></div>
      </main>

      <div class="viewer" :class="{ on: openedClue }" @click.self="closeClueViewer">
        <div v-if="openedClue" class="sheet">
          <img
            v-if="getClueAssetUrl(openedClue)"
            :src="getClueAssetUrl(openedClue)"
            :alt="`${clueStore.clueTitle(openedClue)}线索卡原图`"
            @error="hideBrokenClueImage"
          />
          <div class="txt">
            <span>{{ openedClue.visibility === "public" ? "Public clue · 全员同步" : "Private clue · 仅你可见" }}</span>
            <h3>{{ clueStore.clueTitle(openedClue) }}</h3>
            <p class="cn">{{ openedClue.title }}</p>
            <p class="body">{{ clueStore.clueBody(openedClue) }}</p>
            <p class="src">
              {{ openedClue.tags?.length ? `标签：${openedClue.tags.join("、")}` : "" }}<br />
              图片按 clue_id 推导：/img/clue{{ String(openedClue.id).replace(/\D/g, "") }}.jpg
            </p>
          </div>
        </div>
        <button class="x" type="button" @click="closeClueViewer">✕</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hub select {
  width: 100%;
  padding: 9px 11px;
  border-radius: 10px;
  border: 1px solid var(--line-2);
  background: rgba(4, 6, 11, 0.7);
  color: var(--ink);
  font-size: 12.5px;
}

.hub .obj:disabled,
.hub .loc-act:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.hub .res {
  margin: 0;
}
</style>
