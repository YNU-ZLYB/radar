<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api, fmtTime } from '../api'
import { live } from '../store'
import OilTicker from '../components/OilTicker.vue'
import ArticleCard from '../components/ArticleCard.vue'
import ArticleDrawer from '../components/ArticleDrawer.vue'
import VarietyTrendDrawer from '../components/VarietyTrendDrawer.vue'

const data = ref(null)
const loading = ref(true)
const drawerId = ref(null)
const trendCode = ref(null)
const days = ref(7)
let timer = null

async function load() {
  loading.value = true
  try {
    data.value = await api.get(`/api/v1/dashboard?days=${days.value}`)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(days, load)
watch(() => live.version, () => {
  clearTimeout(timer)
  timer = setTimeout(load, 600)
})

const stats = computed(() => data.value?.stats || {})
const oil = computed(() => data.value?.oil || [])
const varieties = computed(() => data.value?.varieties || [])
const latest = computed(() => data.value?.latest || [])
const sourceInfo = computed(() => {
  const list = (data.value?.sources || []).filter((s) => s.code !== 'manual')
  return { ok: list.filter((s) => s.status === 'ok').length, total: list.length }
})

function openTrend(v) {
  trendCode.value = v.code
}

function cardDir(v) {
  const d = v.daily_summary?.direction
  if (d === 'bullish') return 'pos'
  if (d === 'bearish') return 'neg'
  if (d) return 'neu'
  return v.sentiment > 12 ? 'pos' : v.sentiment < -12 ? 'neg' : 'neu'
}

function cardLabel(v) {
  const c = cardDir(v)
  return c === 'pos' ? '看涨' : c === 'neg' ? '看跌' : '震荡'
}

function cardSize(v) {
  const ds = v.daily_summary
  if (ds && typeof ds.sentiment_llm === 'number') return Math.abs(ds.sentiment_llm)
  return Math.abs(v.sentiment || 0)
}
</script>

<template>
  <div class="container">
    <div class="page-head">
      <div>
        <h1>郑商所期货资讯研判平台</h1>
        <div class="sub">{{ data?.date }} · {{ data?.mode === 'deepseek' ? 'DeepSeek 精判' : '免费模式 · 规则引擎' }}</div>
      </div>
      <button class="btn btn-sm" @click="load" :disabled="loading">{{ loading ? '加载中…' : '刷新' }}</button>
    </div>

    <OilTicker :quotes="oil" />

    <div class="card summary-strip">
      <div class="sum-item"><span>今日入库</span><b>{{ stats.docs_today ?? 0 }}</b></div>
      <div class="sum-item"><span>关联品种</span><b>{{ stats.matched_today ?? 0 }}</b></div>
      <div class="sum-item"><span>已研判</span><b class="val-brand">{{ stats.analyzed_today ?? 0 }}</b></div>
      <div class="sum-item"><span>待研判</span><b :class="{ warn: (stats.pending ?? 0) > 0 }">{{ stats.pending ?? 0 }}</b></div>
      <div class="sum-item"><span>数据源</span><b>{{ sourceInfo.ok }}/{{ sourceInfo.total }}</b></div>
    </div>

    <div class="section-head">
      <h2>全部品种多空速览（{{ varieties.length }}）</h2>
      <div class="days-seg">
        <span class="hint">时间窗</span>
        <div class="seg">
          <button v-for="d in [1, 7, 30]" :key="d" :class="{ active: days === d }" @click="days = d">
            {{ d === 1 ? '今日' : d + ' 天' }}
          </button>
        </div>
      </div>
    </div>
    <section class="card">
      <div class="variety-grid-all">
        <div v-for="v in varieties" :key="v.code" class="variety-card clickable"
             :class="{ empty: !v.count }" @click="openTrend(v)">
          <div class="vc-head">
            <div>
              <h4>{{ v.name }}</h4>
              <span class="code">{{ v.code }}</span>
            </div>
          </div>
          <!-- 只保留：预判方向与幅度（有 DS 研判时以 DS 为准） -->
          <div class="vc-dir" :class="cardDir(v)">
            <span class="dir-word">{{ cardLabel(v) }}</span>
            <span class="dir-unit">强度</span>
            <span class="dir-size">{{ cardSize(v).toFixed(1) }}</span>
            <span class="dir-src">{{ v.daily_summary ? (v.daily_summary.model === 'quote-only' ? '盘面' : 'DS') : '资讯' }}</span>
          </div>

          <!-- 外盘传导（跨市场同向压力） -->
          <div v-if="v.linkage" class="vc-linkage" :class="'lk-' + v.linkage.direction">
            <span class="lk-tag">传导</span>
            <span class="lk-main">{{ v.linkage.summary }}</span>
            <span class="lk-signal">{{ v.linkage.signal > 0 ? '+' : '' }}{{ v.linkage.signal }}</span>
          </div>

          <!-- 每张卡自己的更新时间 -->
          <div class="vc-updated">
            <span>更新 {{ fmtTime(v.updated_at) }}</span>
            <span v-if="v.quote" :class="v.quote.change_pct >= 0 ? 'up' : 'down'">
              行情 {{ v.quote.change_pct > 0 ? '+' : '' }}{{ v.quote.change_pct }}% · {{ fmtTime(v.quote.quoted_at) }}
            </span>
          </div>
        </div>
      </div>
    </section>

    <div class="section-head">
      <h2>最新资讯</h2>
      <router-link to="/feed" class="hint" style="color:var(--brand)">查看全部 →</router-link>
    </div>
    <section class="card">
      <div class="feed-list">
        <ArticleCard v-for="a in latest" :key="a.id" :article="a" @open="drawerId = $event" />
        <div v-if="!latest.length && !loading" class="empty">暂无已关联资讯，可先手工录入一条试试</div>
      </div>
    </section>

    <div class="footer-line">
      <span>数据源 {{ sourceInfo.ok }}/{{ sourceInfo.total }} 正常 · 郑商所官网有反爬</span>
      <router-link to="/sources">采集日志 →</router-link>
      <span class="disclaimer">仅用于信息整理，不构成投资建议</span>
    </div>
  </div>

  <ArticleDrawer v-if="drawerId" :doc-id="drawerId" @close="drawerId = null" />
  <VarietyTrendDrawer v-if="trendCode" :code="trendCode" @close="trendCode = null" />
</template>
