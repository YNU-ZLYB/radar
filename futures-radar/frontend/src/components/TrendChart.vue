<script setup>
/**
 * 纯 SVG 趋势图：品种历史 sentiment 折线 + 累计值 + bull/bear 柱
 * Props: series [{bucket, sentiment, sentiment_running, bullish, bearish, importance_total}]
 */
import { computed } from 'vue'

const props = defineProps({
  series: { type: Array, default: () => [] },
  code: { type: String, default: '' },
  name: { type: String, default: '' },
})

const W = 600
const H = 220
const PAD_L = 42
const PAD_R = 14
const PAD_T = 22
const PAD_B = 28
const plotW = W - PAD_L - PAD_R
const plotH = H - PAD_T - PAD_B

const chart = computed(() => {
  const s = props.series
  if (!s.length) return null
  const xs = s.map((_, i) => PAD_L + (i / Math.max(1, s.length - 1)) * plotW)
  // sentiment: -100~100
  const yMid = PAD_T + plotH / 2
  const ySent = v => yMid - (v / 100) * (plotH / 2)
  // running: auto-scale
  const runMax = Math.max(...s.map(v => Math.abs(v.sentiment_running)), 100)
  const yRun = v => yMid - (v / runMax) * (plotH / 2)

  // Build path for sentiment line
  const sentPath = s.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xs[i].toFixed(1)} ${ySent(p.sentiment).toFixed(1)}`).join(' ')
  const runPath = s.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xs[i].toFixed(1)} ${yRun(p.sentiment_running).toFixed(1)}`).join(' ')

  // Area fill for positive / negative sentiment
  let pos = '', neg = ''
  s.forEach((p, i) => {
    const x = xs[i].toFixed(1)
    const y = ySent(p.sentiment).toFixed(1)
    if (p.sentiment >= 0) {
      pos += (i === 0 ? 'M' : 'L') + ` ${x} ${y} `
    } else {
      neg += (i === 0 ? 'M' : 'L') + ` ${x} ${y} `
    }
  })
  if (pos) pos += `L ${xs[xs.length - 1].toFixed(1)} ${yMid.toFixed(1)} L ${xs[0].toFixed(1)} ${yMid.toFixed(1)} Z`
  if (neg) neg += `L ${xs[xs.length - 1].toFixed(1)} ${yMid.toFixed(1)} L ${xs[0].toFixed(1)} ${yMid.toFixed(1)} Z`

  // Y-axis ticks
  const yTicks = [-100, -50, 0, 50, 100].map(v => ({ v, y: ySent(v).toFixed(1) }))

  // X-axis labels (sparse)
  const labels = s.map((p, i) => {
    const show = i === 0 || i === s.length - 1 || i === Math.round(s.length / 2) || i % Math.max(1, Math.floor(s.length / 5)) === 0
    return { label: p.bucket.slice(5), x: xs[i].toFixed(1), show }
  })

  return { sentPath, runPath, pos, neg, yTicks, labels, yMid: yMid.toFixed(1), runMax }
})
</script>

<template>
  <div class="trend-wrap">
    <div v-if="!series.length" class="empty">暂无历史数据，新资讯进来后会自动累积</div>
    <svg v-else :viewBox="`0 0 ${W} ${H}`" class="trend-svg">
      <!-- zero line -->
      <line :x1="PAD_L" :x2="W - PAD_R" :y1="chart.yMid" :y2="chart.yMid" stroke="#94a3b8" stroke-dasharray="3 3" stroke-width="0.5" />
      <!-- Y axis -->
      <line :x1="PAD_L" :x2="PAD_L" :y1="PAD_T" :y2="H - PAD_B" stroke="#cbd5e1" stroke-width="1" />
      <line :x1="W - PAD_R" :x2="W - PAD_R" :y1="PAD_T" :y2="H - PAD_B" stroke="transparent" />
      <!-- Y ticks -->
      <g v-for="t in chart.yTicks" :key="t.v">
        <line :x1="PAD_L - 4" :x2="PAD_L" :y1="t.y" :y2="t.y" stroke="#cbd5e1" />
        <text :x="PAD_L - 8" :y="t.y" text-anchor="end" dominant-baseline="middle" font-size="10" fill="#64748b">{{ t.v }}%</text>
      </g>
      <!-- X labels -->
      <g v-for="(lb, i) in chart.labels" :key="i">
        <line v-if="lb.show" :x1="lb.x" :x2="lb.x" :y1="H - PAD_B" :y2="H - PAD_B + 4" stroke="#cbd5e1" />
        <text v-if="lb.show" :x="lb.x" :y="H - PAD_B + 14" text-anchor="middle" font-size="10" fill="#64748b">{{ lb.label }}</text>
      </g>
      <!-- Bullish / Bearish fill areas -->
      <path v-if="chart.pos" :d="chart.pos" fill="#ef4444" fill-opacity="0.15" />
      <path v-if="chart.neg" :d="chart.neg" fill="#10b981" fill-opacity="0.15" />
      <!-- Sentiment line -->
      <path :d="chart.sentPath" fill="none" stroke="#ef4444" stroke-width="1.8" />
      <!-- Running line (dashed gray) -->
      <path :d="chart.runPath" fill="none" stroke="#64748b" stroke-width="1.2" stroke-dasharray="4 3" opacity="0.6" />
      <!-- Points -->
      <g v-for="(p, i) in series" :key="'pt' + i">
        <circle
          :cx="PAD_L + (i / Math.max(1, series.length - 1)) * plotW"
          :cy="PAD_T + plotH / 2 - (p.sentiment / 100) * (plotH / 2)"
          r="2.5"
          :fill="p.sentiment >= 0 ? '#ef4444' : '#10b981'"
        />
      </g>
    </svg>
    <div v-if="chart" class="trend-legend">
      <span><b style="color:#ef4444">▬</b> 当日情绪 sentiment</span>
      <span><b style="color:#64748b">╌╌</b> 累计加权 sentiment_running（重要日子权重更大）</span>
      <span class="hint">样本数 {{ series.length }} 天 · 每点 bull {{ series.reduce((a, b) => a + b.bullish, 0) }} / bear {{ series.reduce((a, b) => a + b.bearish, 0) }}</span>
    </div>
  </div>
</template>

<style scoped>
.trend-wrap { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 8px 4px 4px; }
.trend-svg { width: 100%; height: auto; display: block; }
.trend-legend { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11px; color: #64748b; padding: 4px 10px 2px; }
.trend-legend b { margin-right: 3px; }
.trend-legend .hint { color: #94a3b8; margin-left: auto; }
</style>
