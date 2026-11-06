<script setup>
import { computed } from 'vue'

const props = defineProps({ value: { type: Number, default: 0 } })
const color = computed(() => (props.value > 5 ? 'var(--bull)' : props.value < -5 ? 'var(--bear)' : 'var(--neutral)'))
const width = computed(() => Math.min(100, Math.max(6, Math.abs(props.value))))
</script>

<template>
  <div class="sentiment">
    <div class="sentiment-bar">
      <span :style="{ width: width / 2 + '%', background: color, [value >= 0 ? 'left' : 'right']: '50%' }"></span>
    </div>
    <div class="sentiment-num" :style="{ color }">{{ value > 0 ? '+' : '' }}{{ value.toFixed(0) }}</div>
  </div>
</template>
