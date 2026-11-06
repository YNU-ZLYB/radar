<script setup>
import { computed } from 'vue'
import { highlightParts } from '../highlight'

const props = defineProps({ text: { type: String, default: '' } })
const parts = computed(() => highlightParts(props.text))
</script>

<template>
  <span><template v-for="(p, i) in parts" :key="i"><span v-if="p.hot" class="hot">{{ p.text }}</span><template v-else>{{ p.text }}</template></template></span>
</template>
