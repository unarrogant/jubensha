import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { getMyClues } from "../services/api";

// 线索墙：后端判定我确实发现线索后，才把 clue_ids 随消息推送下来，
// 这里按“进入我墙里的顺序”倒序展示，最新的一条始终在最上面。
export const useClueStore = defineStore("clues", () => {
  const clues = ref([]);
  const discoveryOrder = ref([]);
  const newIds = ref([]);
  let seeded = false;
  let highlightTimer = null;

  const wall = computed(() => {
    const rank = new Map(discoveryOrder.value.map((id, index) => [id, index]));
    return [...clues.value].sort(
      (left, right) => (rank.get(right.id) ?? -1) - (rank.get(left.id) ?? -1),
    );
  });

  const count = computed(() => clues.value.length);
  const clueOf = (clueId) => clues.value.find((clue) => clue.id === clueId) || null;
  const clueTitle = (clue) => clue?.title_zh || clue?.title || "";
  const clueBody = (clue) => clue?.content_zh || clue?.content || "";

  async function refresh(roomId, playerId, revealedIds = []) {
    const next = await getMyClues(roomId, playerId);
    const known = new Set(clues.value.map((clue) => clue.id));
    const added = next.filter((clue) => !known.has(clue.id)).map((clue) => clue.id);
    const missing = revealedIds.filter(
      (clueId) => !known.has(clueId) && !added.includes(clueId),
    );
    clues.value = next;

    // 首次读取只建立顺序，不让旧线索集体高亮。
    if (!seeded) {
      seeded = true;
      discoveryOrder.value = added;
      return [];
    }

    const fresh = [...added, ...missing];
    if (fresh.length) {
      discoveryOrder.value = [...discoveryOrder.value, ...fresh];
      newIds.value = [...fresh];
      if (highlightTimer) window.clearTimeout(highlightTimer);
      highlightTimer = window.setTimeout(() => {
        newIds.value = [];
      }, 6000);
    }
    return fresh;
  }

  function reset() {
    clues.value = [];
    discoveryOrder.value = [];
    newIds.value = [];
    seeded = false;
    if (highlightTimer) window.clearTimeout(highlightTimer);
    highlightTimer = null;
  }

  return {
    clues, wall, newIds, count,
    clueOf, clueTitle, clueBody, refresh, reset,
  };
});
