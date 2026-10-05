<script setup>
import { computed, ref } from "vue";

const props = defineProps({
  text: {
    type: String,
    default: "",
  },
  vocabulary: {
    type: Array,
    default: () => [],
  },
});

const activeEntry = ref(null);

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const vocabularyLookup = computed(() => {
  const lookup = new Map();

  for (const entry of props.vocabulary) {
    const forms = [entry?.term, ...(entry?.forms || [])];
    for (const form of forms) {
      if (typeof form === "string" && form.trim()) {
        lookup.set(form.trim().toLocaleLowerCase(), entry);
      }
    }
  }

  return lookup;
});

const textParts = computed(() => {
  const source = props.text || "";
  const forms = [...vocabularyLookup.value.keys()]
    .sort((left, right) => right.length - left.length)
    .map(escapeRegExp);

  if (!source || !forms.length) {
    return [{ type: "text", text: source }];
  }

  const matcher = new RegExp(`\\b(?:${forms.join("|")})\\b`, "gi");
  const parts = [];
  let cursor = 0;
  let match;

  while ((match = matcher.exec(source)) !== null) {
    if (match.index > cursor) {
      parts.push({ type: "text", text: source.slice(cursor, match.index) });
    }

    parts.push({
      type: "term",
      text: match[0],
      entry: vocabularyLookup.value.get(match[0].toLocaleLowerCase()),
    });
    cursor = matcher.lastIndex;
  }

  if (cursor < source.length) {
    parts.push({ type: "text", text: source.slice(cursor) });
  }

  return parts.length ? parts : [{ type: "text", text: source }];
});

function toggleEntry(entry) {
  activeEntry.value = activeEntry.value === entry ? null : entry;
}
</script>

<template>
  <span class="annotated-text">
    <template v-for="(part, index) in textParts" :key="`${part.type}-${index}-${part.text}`">
      <button
        v-if="part.type === 'term'"
        type="button"
        class="annotated-word"
        :aria-expanded="activeEntry === part.entry"
        :title="`View annotation for ${part.entry?.term || part.text}`"
        @click.stop="toggleEntry(part.entry)"
      >{{ part.text }}</button>
      <template v-else>{{ part.text }}</template>
    </template>

    <span v-if="activeEntry" class="vocabulary-note" role="note">
      <span class="vocabulary-note__heading">
        <strong>{{ activeEntry.term }}</strong>
        <button type="button" aria-label="Close annotation" @click.stop="activeEntry = null">×</button>
      </span>
      <span v-if="activeEntry.pronunciation || activeEntry.part_of_speech" class="vocabulary-note__meta">
        {{ [activeEntry.pronunciation, activeEntry.part_of_speech].filter(Boolean).join(" · ") }}
      </span>
      <span class="vocabulary-note__meaning">{{ activeEntry.meaning }}</span>
      <span v-if="activeEntry.example" class="vocabulary-note__example">{{ activeEntry.example }}</span>
    </span>
  </span>
</template>
