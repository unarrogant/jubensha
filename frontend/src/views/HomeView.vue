<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { Check, RefreshCw } from "@lucide/vue";
import HubHeader from "../components/HubHeader.vue";
import { useRoomStore } from "../stores/room";

const route = useRoute();
const router = useRouter();
const roomStore = useRoomStore();
const { scripts, waitingRooms, selectedScriptId, selectedScript, catalogLoading, roomsLoading } =
  storeToRefs(roomStore);

const hostName = ref("");
const joinName = ref("");
const roomCode = ref("");
const joinMode = ref("list");
const submitting = ref(false);
const errorMessage = ref("");
const coverFailures = ref({});
let refreshTimer = null;

const hallTheme = computed(() =>
  roomStore.getThemeVars(selectedScript.value || scripts.value[0]),
);

function scriptOf(room) {
  return roomStore.getScript(room.script_id);
}

function pick(scriptId) {
  roomStore.selectScript(scriptId);
  errorMessage.value = "";
}

function setJoinMode(mode) {
  joinMode.value = mode;
}

function prepareJoin(room) {
  roomCode.value = room.id;
  joinMode.value = "code";
  errorMessage.value = "";
  document.getElementById("join-card")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function handleCreate() {
  errorMessage.value = "";
  if (!selectedScript.value) {
    errorMessage.value = "请先从剧本大厅选择一部剧本";
    return;
  }
  if (!hostName.value.trim()) {
    errorMessage.value = "请输入你的玩家昵称";
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
    errorMessage.value = "请输入房间号和玩家昵称";
    return;
  }

  submitting.value = true;
  try {
    const result = await roomStore.joinExistingRoom(roomCode.value, joinName.value.trim());
    await router.push(`/lobby/${result.roomId}`);
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    submitting.value = false;
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
  errorMessage.value = "";
  try {
    await Promise.all([roomStore.loadScripts(), roomStore.loadWaitingRooms()]);
  } catch (error) {
    errorMessage.value = error.message;
  }

  if (route.query.room) {
    roomCode.value = String(route.query.room).toUpperCase();
    joinMode.value = "code";
  }

  refreshTimer = window.setInterval(refreshRoomsSilently, 6000);
});

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer);
});
</script>

<template>
  <div class="hub" :style="hallTheme">
    <div class="hub-inner">
      <HubHeader>
        <template #center>
          <nav class="topnav">
            <a href="#scripts">剧本大厅</a>
            <a href="#open-rooms">开放房间</a>
            <RouterLink to="/admin/login">管理端</RouterLink>
          </nav>
        </template>
        <template #actions>
          <span class="pill"><span class="dot"></span>服务在线</span>
        </template>
      </HubHeader>

      <main class="wrap">
        <section class="hall-head">
          <span class="overline">Tonight · Four Stories Open</span>
          <h1>灯已经暗下，<em>{{ scripts.length }} 出戏同时在等</em></h1>
          <p>不必搜索，不必筛选。挑一部剧本，AI 主持人推进流程、判定搜证、发放线索，你和朋友进入同一个现场。</p>
          <div class="hall-stats">
            <span>本晚上演 <b>{{ String(scripts.length).padStart(2, "0") }}</b> 部</span>
            <span>等待入席 <b>{{ String(waitingRooms.length).padStart(2, "0") }}</b> 间</span>
            <span>全程 <b>AI</b> 主持</span>
          </div>
        </section>

        <div v-if="errorMessage" class="alert" role="alert">
          <span>{{ errorMessage }}</span>
          <button type="button" @click="errorMessage = ''">关闭</button>
        </div>

        <section id="scripts">
          <div class="sec-head">
            <h2>剧本大厅</h2>
            <small>点击卡片选中，下方创建区与整站配色同步切换</small>
          </div>

          <div v-if="catalogLoading" class="loader"><i></i><span>正在读取剧本库…</span></div>
          <div v-else-if="!scripts.length" class="empty">
            <strong>剧本库暂时为空</strong>
            <span>content 目录里还没有已发布的剧本，请稍后重新进入。</span>
          </div>
          <div v-else class="scripts">
            <article
              v-for="script in scripts"
              :key="script.id"
              class="script"
              :class="{ sel: selectedScriptId === script.id }"
              :style="roomStore.getScriptCardVars(script)"
              role="button"
              tabindex="0"
              @click="pick(script.id)"
              @keydown.enter.prevent="pick(script.id)"
            >
              <div class="poster">
                <img
                  v-if="!coverFailures[script.id]"
                  :src="roomStore.getCoverUrl(script)"
                  :alt="`${roomStore.getDisplayName(script)}封面`"
                  @error="coverFailures[script.id] = true"
                />
                <span v-else class="poster-fallback">{{ roomStore.getDisplayName(script).slice(0, 1) }}</span>
                <div class="poster-top">
                  <span class="kind">{{ roomStore.getScriptTypeLabel(script) }}</span>
                  <span class="tick"><Check :size="13" /></span>
                </div>
                <div class="poster-name">
                  <span>V{{ script.version }} · {{ (script.language || "en").toUpperCase() }}</span>
                  <b>{{ roomStore.getDisplayName(script) }}</b>
                </div>
              </div>
              <div class="script-body">
                <p class="sum">{{ roomStore.getDisplaySummary(script) }}</p>
                <div class="kv">
                  <span><i>{{ script.player_count }}</i> 人</span>
                  <span><i>{{ script.estimated_minutes }}</i> 分钟</span>
                  <span><i>AI</i> 全程主持</span>
                </div>
                <div class="dm-row"><span class="dot"></span>主持人 <b>{{ roomStore.getDmName(script) }}</b></div>
                <button class="choose" type="button">
                  {{ selectedScriptId === script.id ? "已选择此剧本" : "选择此剧本" }}
                </button>
              </div>
            </article>
          </div>
        </section>

        <div class="duo">
          <section class="card create" id="quick-start">
            <span class="overline">Create Room</span>
            <h3>创建房间</h3>

            <div v-if="selectedScript" class="echo">
              <img :src="roomStore.getCoverUrl(selectedScript)" :alt="roomStore.getDisplayName(selectedScript)" />
              <div>
                <b>{{ roomStore.getDisplayName(selectedScript) }}</b>
                <span>{{ selectedScript.title }} · v{{ selectedScript.version }}</span>
              </div>
            </div>
            <div v-else class="create-empty">先在上方选择一部剧本，创建区会同步它的封面与人数要求。</div>

            <div v-if="selectedScript" class="req">
              <span>需要 <b>{{ selectedScript.player_count }}</b> 名玩家</span>
              <span>预计 <b>{{ selectedScript.estimated_minutes }}</b> 分钟</span>
              <span><b>AI</b> 主持 · {{ roomStore.getDmName(selectedScript) }}</span>
            </div>

            <label class="field" for="host-name">你的玩家昵称</label>
            <input
              id="host-name"
              v-model="hostName"
              class="inp"
              maxlength="20"
              autocomplete="nickname"
              placeholder="其他玩家会看到这个名字"
            />
            <button
              class="btn-main"
              type="button"
              :disabled="submitting || !selectedScript"
              @click="handleCreate"
            >
              {{ submitting ? "正在创建" : "基于当前剧本创建房间" }}
            </button>
            <p class="note">创建后进入等待大厅，房间数据会写入 script_id、剧本名称、版本、封面与规定人数。</p>
          </section>

          <section class="card join-card" id="join-card">
            <span class="overline">Open Rooms</span>
            <h3>加入房间</h3>

            <div class="join-tabs">
              <button :class="{ on: joinMode === 'list' }" type="button" @click="setJoinMode('list')">
                从开放列表选择
              </button>
              <button :class="{ on: joinMode === 'code' }" type="button" @click="setJoinMode('code')">
                输入房间号
              </button>
            </div>

            <template v-if="joinMode === 'list'">
              <div class="sec-head" style="margin: 0 0 6px">
                <small>共 {{ waitingRooms.length }} 间 · 每 6 秒同步</small>
                <button class="btn-ghost" type="button" :disabled="roomsLoading" @click="roomStore.loadWaitingRooms">
                  <RefreshCw :size="13" :class="{ spinning: roomsLoading }" /> 刷新
                </button>
              </div>

              <div v-if="!waitingRooms.length" class="create-empty">
                当前没有公开房间。选中一部剧本，创建今晚的第一间房。
              </div>
              <button
                v-for="room in waitingRooms"
                :key="room.id"
                class="room"
                type="button"
                @click="prepareJoin(room)"
              >
                <img
                  v-if="scriptOf(room) && !coverFailures[room.id]"
                  :src="roomStore.getCoverUrl(scriptOf(room))"
                  :alt="roomStore.getDisplayName(scriptOf(room))"
                  @error="coverFailures[room.id] = true"
                />
                <span v-else class="room-fallback">
                  {{ roomStore.getDisplayName(scriptOf(room)).slice(0, 1) || "?" }}
                </span>
                <div>
                  <b>{{ roomStore.getDisplayName(scriptOf(room)) || room.script_id }}</b>
                  <small>房主 {{ room.host_name }} · {{ room.id }}</small>
                  <div class="track" style="margin-top: 7px">
                    <i :style="{ width: `${Math.min(100, (room.player_count / room.required_players) * 100)}%` }"></i>
                  </div>
                </div>
                <div class="capacity-cell">
                  <span class="num">{{ room.player_count }} / {{ room.required_players }}</span>
                  <small>需要 {{ room.required_players }} 人</small>
                </div>
                <span class="st-badge" :class="room.player_count >= room.required_players ? 'st-full' : 'st-wait'">
                  {{ room.player_count >= room.required_players ? "人数已满" : "等待玩家" }}
                </span>
              </button>
            </template>

            <form v-else class="code-form" @submit.prevent="handleJoin">
              <div>
                <label class="field" for="room-code">8 位房间号</label>
                <input
                  id="room-code"
                  v-model="roomCode"
                  class="inp"
                  maxlength="8"
                  autocomplete="off"
                  placeholder="A3F7K2QD"
                  style="font-family: var(--mono); letter-spacing: .18em"
                />
              </div>
              <div>
                <label class="field" for="join-name">玩家昵称</label>
                <input id="join-name" v-model="joinName" class="inp" maxlength="20" placeholder="例如：陈屿" />
              </div>
              <button class="btn-ghost" type="submit" style="height: 43px" :disabled="submitting">
                {{ submitting ? "正在加入" : "进入" }}
              </button>
            </form>
          </section>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.spinning { animation: hubspin 1s linear infinite; }
.room .poster-fallback { display: grid; place-items: center; font-family: var(--serif); }
</style>
