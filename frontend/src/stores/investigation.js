import { computed, ref } from "vue";
import { defineStore } from "pinia";
import {
  enterInvestigationLocation,
  getInvestigationLocations,
  inspectInvestigationObject,
} from "../services/api";

// 搜证状态：地点、进入后的物品、我自己的搜查结果。
// 后端只在我进入过地点之后才下发物品名，所以这里不存在“哪些地点藏线索”的信息。
export const useInvestigationStore = defineStore("investigation", () => {
  const locations = ref([]);
  const enteredIds = ref([]);
  const objectsByLocation = ref({});
  // objectId -> 我看到的结论文字
  const myResults = ref({});
  // objectId -> 已被别人翻过的物品
  const spentIds = ref([]);
  const loading = ref(false);
  const error = ref("");

  const isEntered = (locationId) => enteredIds.value.includes(locationId);
  const objectsOf = (locationId) => objectsByLocation.value[locationId] || [];
  const locationOf = (locationId) =>
    locations.value.find((location) => location.id === locationId) || null;

  const progressOf = computed(() => (locationId) => {
    const objects = objectsOf(locationId);
    const done = objects.filter(
      (object) => object.id in myResults.value || spentIds.value.includes(object.id),
    ).length;
    return { done, total: objects.length };
  });

  const statusOf = computed(() => (objectId) => {
    if (objectId in myResults.value) return "mine";
    if (spentIds.value.includes(objectId)) return "gone";
    return "free";
  });

  function reset() {
    locations.value = [];
    enteredIds.value = [];
    objectsByLocation.value = {};
    myResults.value = {};
    spentIds.value = [];
    error.value = "";
  }

  function rememberLocation(location) {
    if (!location?.id) return;
    if (!enteredIds.value.includes(location.id)) enteredIds.value.push(location.id);
    objectsByLocation.value = {
      ...objectsByLocation.value,
      [location.id]: location.objects || [],
    };
  }

  async function loadLocations(roomId, playerId) {
    loading.value = true;
    try {
      const data = await getInvestigationLocations(roomId, playerId);
      locations.value = data.locations || [];
      enteredIds.value = data.entered_location_ids || [];
      const nextObjects = {};
      for (const location of locations.value) {
        if (location.objects?.length) nextObjects[location.id] = location.objects;
      }
      objectsByLocation.value = nextObjects;
      // 刷新前翻过的物品只剩 id，结果文字留在对话记录里。
      const restored = { ...myResults.value };
      for (const objectId of data.searched_object_ids || []) {
        if (!(objectId in restored)) {
          restored[objectId] = "你之前翻过这里，主持人的那句话还在上面的对话里。";
        }
      }
      myResults.value = restored;
      error.value = "";
    } catch (requestError) {
      // 介绍阶段还没有开放搜证，接口返回 400 时只保留提示文字。
      error.value = requestError.message;
    } finally {
      loading.value = false;
    }
  }

  async function enter(roomId, playerId, locationId) {
    const result = await enterInvestigationLocation(roomId, playerId, locationId);
    if (!isEntered(locationId)) enteredIds.value.push(locationId);
    objectsByLocation.value = {
      ...objectsByLocation.value,
      [locationId]: result.objects || [],
    };
    error.value = "";
    return result;
  }

  async function inspect(roomId, playerId, locationId, objectId, objectText) {
    const result = await inspectInvestigationObject(roomId, playerId, locationId, objectText);
    if (result.already_discovered && !spentIds.value.includes(objectId)) {
      spentIds.value = [...spentIds.value, objectId];
    } else {
      myResults.value = { ...myResults.value, [objectId]: result.message };
    }
    error.value = "";
    return result;
  }

  return {
    locations, enteredIds, objectsByLocation, myResults, spentIds, loading, error,
    isEntered, objectsOf, locationOf, progressOf, statusOf,
    reset, loadLocations, enter, inspect,
  };
});
