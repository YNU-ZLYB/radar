<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, fmtNum } from '../api'
import { live } from '../store'
import SentimentBar from '../components/SentimentBar.vue'
import ArticleCard from '../components/ArticleCard.vue'
import ArticleDrawer from '../components/ArticleDrawer.vue'

const route = useRoute()
const code = computed(() => route.params.code.toUpperCase())
const detail = ref(null)
const items = ref([])
const direction = ref('all')
const drawerId = ref(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    detail.value = await api.variety(code.value)
    const res = await api.feed({
      variety: code.value, direction: direction.value, page_size: 30, days: 30, sort: 'importance',
    })
    items.value = res.items
  } finally {
    loading.value = false
  }
}

function setDirection(d) { direction.value = d; load() }

onMounted(load)
watch(code, load)
watch(direction, load)
watch(() => live.version, () => {
  if (live.lastEvent?.event === 'article_new' || live.lastEvent?.event === 'analysis_update') load()
})

const oilQuotes = computed(() => (detail.value?.oil || []).filter((q) => q.price !== null))
</script>

<template>
  <div class="container">
    <div class="page-head">
      <div>
        <div class="row" style="gap:10px">
          <router-link to="/feed" class="small" style="color:var(--brand)">← 信息流</router-link>
          <span class="chip">{{ detail?.sector }}</span>
        </div>
        <h1 style="margin-top:6px">{{ detail?.name }} <span class="muted" style="font-size:14px">{{ code }}</span></h1>
        <div class="sub">{{ detail?.description }}</div>
      </div>
      <div style="min-width:220px">
        <div class="tiny muted" style="margin-bottom:4px">今日多空情绪</div>
        <SentimentBar :value="detail?.sentiment || 0" />
        <div class="tiny muted" style="margin-top:4px">基于 {{ detail?.count || 0 }} 条评分</div>
      </div>
    </div>

    <section class="card">
      <div class="card-head">
        <h3>品种资讯</h3>
        <div class="tabs">
          <span class="tab" :class="{ active: direction === 'all' }" @click="setDirection('all')">全部</span>
          <span class="tab" :class="{ active: direction === 'bullish' }" @click="setDirection('bullish')">利多</span>
          <span class="tab" :class="{ active: direction === 'bearish' }" @click="setDirection('bearish')">利空</span>
        </div>
      </div>
      <div class="feed-list">
        <ArticleCard v-for="a in items" :key="a.id" :article="a" @open="drawerId = $event" />
        <div v-if="loading" class="loading">加载中…</div>
        <div v-else-if="!items.length" class="empty">该品种近 30 天暂无相关信息</div>
      </div>
    </section>

    <details class="card details-card">
      <summary>
        <span>影响因子权重 · 原油参考</span>
      </summary>
      <div class="details-body">
        <section v-if="detail">
          <div class="tiny muted" style="margin-bottom:10px">因子权重用于排序与解释</div>
          <div v-for="f in detail.factors" :key="f.name" style="margin-bottom:11px">
            <div class="row" style="justify-content:space-between; margin-bottom:3px">
              <div class="row" style="gap:6px"><span class="factor-dot" :style="{ background: f.color }"></span><span class="small">{{ f.name }}</span></div>
              <span class="tiny muted">{{ (f.weight * 100).toFixed(0) }}%</span>
            </div>
            <div class="sentiment-bar"><span :style="{ width: (f.weight * 100) + '%', left: 0, background: f.color, opacity: .65 }"></span></div>
            <div v-if="f.keywords?.length" class="tiny muted" style="margin-top:3px">{{ f.keywords.slice(0, 6).join(' · ') }}</div>
          </div>
        </section>

        <section>
          <div class="row" style="justify-content:space-between; margin-bottom:10px">
            <div class="tiny muted">原油参考</div>
            <span class="badge" :class="detail?.oil_correlation?.level === '中' ? 'bull' : 'gray'">
              相关性 {{ detail?.oil_correlation?.level }}
            </span>
          </div>
          <div v-for="q in oilQuotes" :key="q.benchmark" class="row" style="justify-content:space-between; padding:5px 0; border-bottom:1px solid #f1f5f9">
            <span class="small">{{ q.name }}</span>
            <span class="small mono" :class="q.change_pct > 0 ? 'up' : q.change_pct < 0 ? 'down' : ''">
              {{ fmtNum(q.price, q.benchmark === 'SC' ? 1 : 2) }}
              <span class="tiny">（{{ q.change_pct > 0 ? '+' : '' }}{{ fmtNum(q.change_pct) }}%）</span>
            </span>
          </div>
          <div class="tiny muted" style="margin-top:8px">{{ detail?.oil_correlation?.note }}</div>
        </section>
      </div>
    </details>
  </div>

  <ArticleDrawer v-if="drawerId" :doc-id="drawerId" @close="drawerId = null" />
</template>
