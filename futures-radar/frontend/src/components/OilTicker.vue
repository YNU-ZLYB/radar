<script setup>
import { computed } from 'vue'
import { fmtNum } from '../api'

const props = defineProps({ quotes: { type: Array, default: () => [] } })

function sparkPath(points, w = 66, h = 24) {
  if (!points || points.length < 2) return ''
  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = max - min || 1
  return points.map((p, i) => {
    const x = (i / (points.length - 1)) * w
    const y = h - ((p - min) / range) * h
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

const items = computed(() => props.quotes.map((q) => ({
  ...q,
  path: sparkPath(q.spark),
  cls: q.change_pct > 0 ? 'up' : q.change_pct < 0 ? 'down' : '',
  sign: q.change_pct > 0 ? '+' : '',
})))
</script>

<template>
  <div class="oil-bar">
    <div v-for="q in items" :key="q.benchmark" class="oil-item">
      <div class="oil-name">
        <span>{{ q.name }}</span>
        <span>{{ q.available === false ? '待接入' : q.benchmark }}</span>
      </div>
      <template v-if="q.price !== null">
        <div class="oil-price">{{ fmtNum(q.price, q.benchmark === 'SC' ? 1 : 2) }}<span class="oil-unit">{{ q.unit }}</span></div>
        <div class="oil-change" :class="q.cls">{{ q.sign }}{{ fmtNum(q.change_pct) }}% <span class="muted tiny">较昨收</span></div>
        <svg class="oil-spark" width="66" height="24" viewBox="0 0 66 24">
          <path :d="q.path" fill="none" :stroke="q.change_pct >= 0 ? '#ff8a8a' : '#4ade80'" stroke-width="1.5" />
        </svg>
      </template>
      <div v-else class="oil-na">{{ q.note || '暂无数据' }}</div>
    </div>
  </div>
</template>
