<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import {
  Bot,
  Check,
  Clock3,
  DoorOpen,
  LogIn,
  Plus,
  RefreshCw,
  Search,
  Users,
  X,
} from "@lucide/vue";
import AppHeader from "../components/AppHeader.vue";
import { useRoomStore } from "../stores/room";

const route = useRoute();
const router = useRouter();
const roomStore = useRoomStore();
const {
  scripts,
  waitingRooms,
  selectedScriptId,
  selectedScript,
  catalogLoading,
  roomsLoading,
} = storeToRefs(roomStore);

const mode = ref("create");
const hostName = ref("");
const roomCode = ref("");
const joinName = ref("");
const searchText = ref("");
const submitting = ref(false);
const errorMessage = ref("");
const coverFailures = ref({});
let refreshTimer = null;

const filteredScripts = computed(() => {
  const keyword = searchText.value.trim().toLowerCase();
  if (!keyword) return scripts.value;
  return scripts.value.filter((script) =>
    [script.title, script.summary, ...(script.tags || [])]
      .join(" ")
      .toLowerCase()
      .includes(keyword),
  );
});

function getRoomScript(room) {
  return roomStore.getScript(room.script_id);
}

function chooseScript(scriptId) {
  roomStore.selectScript(scriptId);
  mode.value = "create";
  errorMessage.value = "";
}

function prepareJoin(room) {
  roomCode.value = room.id;
  mode.value = "join";
  errorMessage.value = "";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

 async function handleCreate() {
  errorMessage.value = "";
  if (!selectedScript.value) {
    errorMessage.value = "请先从剧本库选择一个剧本";
    return;
  }
  if (!hostName.value.trim()) {
    errorMessage.value = "请输入你的玩家名称";
    return;
  }

  submitting.value = true;
  try {
    const room = await roomStore.createNewRoom(hostName.value.trim());
    await router.push(`/lobby/${room.id}`);
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    submitting.value = false;
  }
}

async function handleJoin() {
  errorMessage.value = "";
  if (!roomCode.value.trim() || !joinName.value.trim()) {
    errorMessage.value = "请输入房间号和玩家名称";
    return;
  }

  submitting.value = true;
  try {
    const result = await roomStore.joinExistingRoom(
      roomCode.value,
      joinName.value.trim(),
    );
    await router.push(`/lobby/${result.roomId}`);
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    submitting.value = false;
  }
}

async function loadPlatform() {
  errorMessage.value = "";
  try {
    await Promise.all([roomStore.loadScripts(), roomStore.loadWaitingRooms()]);
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function refreshRoomsSilently() {
  try {
    await roomStore.loadWaitingRooms();
  } catch {
    // 保留最后一次成功获取的房间列表。
  }
}

onMounted(async () => {
  await loadPlatform();
  if (route.query.room) {
    roomCode.value = String(route.query.room).toUpperCase();
    mode.value = "join";
  }
  refreshTimer = window.setInterval(refreshRoomsSilently, 6000);
});

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer);
});
</script>

<template>
  <div class="app-shell">
    <AppHeader>
      <template #center>
        <nav class="header-nav" aria-label="主要导航">
          <a class="active" href="#scripts">剧本库</a>
          <a href="#rooms">公开房间</a>
        </nav>
      </template>
    </AppHeader>

    <main class="hub-main">
      <section class="hub-heading">
        <div>
          <span class="overline">AI MYSTERY LOBBY</span>
          <h1>今晚，开一局好戏</h1>
          <p>选择剧本，召集同局玩家。人数到齐后，AI 主持人将接管流程。</p>
        </div>
        <dl class="hub-summary">
          <div><dt>{{ scripts.length }}</dt><dd>可用剧本</dd></div>
          <div><dt>{{ waitingRooms.length }}</dt><dd>等待房间</dd></div>
        </dl>
      </section>

      <section class="quick-panel" aria-label="创建或加入房间">
        <div class="mode-switch">
          <button :class="{ active: mode === 'create' }" type="button" @click="mode = 'create'">
            <Plus :size="17" />创建房间
          </button>
          <button :class="{ active: mode === 'join' }" type="button" @click="mode = 'join'">
            <LogIn :size="17" />加入房间
          </button>
        </div>

        <form v-if="mode === 'create'" class="quick-form" @submit.prevent="handleCreate">
          <div class="chosen-script">
            <span>当前剧本</span>
            <strong>{{ selectedScript?.title || "尚未选择" }}</strong>
          </div>
          <label>
            <span>你的玩家名称</span>
            <input v-model="hostName" maxlength="20" autocomplete="nickname" placeholder="例如：林默" />
          </label>
          <button class="button button-primary" :disabled="submitting || !selectedScript">
            <DoorOpen :size="17" />{{ submitting ? "正在创建" : "创建房间" }}
          </button>
        </form>

        <form v-else class="quick-form join-form" @submit.prevent="handleJoin">
          <label>
            <span>房间号</span>
            <input v-model="roomCode" maxlength="8" autocomplete="off" placeholder="8 位房间号" />
          </label>
          <label>
            <span>你的玩家名称</span>
            <input v-model="joinName" maxlength="20" autocomplete="nickname" placeholder="其他玩家会看到此名称" />
          </label>
          <button class="button button-primary" :disabled="submitting">
            <LogIn :size="17" />{{ submitting ? "正在加入" : "进入房间" }}
          </button>
        </form>

        <div v-if="errorMessage" class="inline-alert">
          <span>{{ errorMessage }}</span>
          <button type="button" aria-label="关闭" @click="errorMessage = ''"><X :size="16" /></button>
        </div>
      </section>

      <section id="scripts" class="content-section">
        <header class="section-bar">
          <div>
            <span class="overline">SCRIPT LIBRARY</span>
            <h2>选择本次剧本</h2>
          </div>
          <label class="search-box">
            <Search :size="16" />
            <input v-model="searchText" aria-label="搜索剧本" placeholder="搜索剧本或标签" />
          </label>
        </header>

        <div v-if="catalogLoading" class="loading-state"><span>正在读取剧本库…</span></div>
        <div v-else-if="!filteredScripts.length" class="empty-state">
          <Search :size="24" /><strong>没有找到剧本</strong><span>换一个关键词试试。</span>
        </div>
        <div v-else class="script-grid">
          <article
            v-for="script in filteredScripts"
            :key="script.id"
            class="script-card"
            :class="{ selected: selectedScriptId === script.id }"
          >
            <button class="script-poster" type="button" @click="chooseScript(script.id)">
              <img
                v-if="!coverFailures[script.id]"
                :src="roomStore.getCoverUrl(script)"
                :alt="`${script.title}封面`"
                @error="coverFailures[script.id] = true"
              />
              <span v-else class="poster-fallback">{{ script.title.slice(0, 1) }}</span>
              <span class="script-state">{{ script.status === "draft" ? "测试版" : "可开局" }}</span>
              <span v-if="selectedScriptId === script.id" class="selected-mark"><Check :size="13" />已选择</span>
            </button>

            <div class="script-content">
              <div class="script-title-row">
                <div><span>{{ script.type === "murder_mystery" ? "推理剧本" : script.type }}</span><h3>{{ script.title }}</h3></div>
                <span>v{{ script.version }}</span>
              </div>
              <p>{{ script.summary }}</p>
              <div class="meta-row">
                <span><Users :size="14" />{{ script.player_count }} 人</span>
                <span><Clock3 :size="14" />{{ script.estimated_minutes }} 分钟</span>
                <span><Bot :size="14" />{{ script.agent_profile?.display_name }}</span>
              </div>
              <div class="tag-row"><span v-for="tag in script.tags" :key="tag">{{ tag }}</span></div>
              <button class="text-action" type="button" @click="chooseScript(script.id)">
                <Check v-if="selectedScriptId === script.id" :size="14" />
                {{ selectedScriptId === script.id ? "已选中此剧本" : "选择此剧本" }}
              </button>
            </div>
          </article>
        </div>
      </section>

      <section id="rooms" class="content-section room-section">
        <header class="section-bar">
          <div><span class="overline">OPEN ROOMS</span><h2>等待玩家加入</h2></div>
          <button class="icon-text-button" type="button" :disabled="roomsLoading" @click="roomStore.loadWaitingRooms">
            <RefreshCw :size="15" :class="{ spinning: roomsLoading }" />刷新房间
          </button>
        </header>

        <div v-if="waitingRooms.length" class="room-list">
          <article v-for="room in waitingRooms" :key="room.id" class="room-item">
            <div class="room-code-block"><span>房间号</span><strong>{{ room.id }}</strong></div>
            <div class="room-script-name"><strong>{{ getRoomScript(room)?.title || room.script_id }}</strong><span>{{ room.host_name }} 创建</span></div>
            <div class="room-capacity">
              <div><span>当前人数</span><strong>{{ room.player_count }} / {{ room.required_players }}</strong></div>
              <span class="capacity-track"><i :style="{ width: `${(room.player_count / room.required_players) * 100}%` }"></i></span>
            </div>
            <button class="button button-secondary" type="button" @click="prepareJoin(room)">加入</button>
          </article>
        </div>
        <div v-else-if="!roomsLoading" class="empty-state">
          <DoorOpen :size="24" /><strong>当前没有公开房间</strong><span>选择剧本，创建今晚的第一间房。</span>
        </div>
      </section>
    </main>
  </div>
</template>
