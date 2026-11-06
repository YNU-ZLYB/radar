<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { live } from '../store'
import ArticleCard from '../components/ArticleCard.vue'
import ArticleDrawer from '../components/ArticleDrawer.vue'

const FACTORS = ['供给', '需求', '库存', '成本', '政策', '天气', '宏观', '资金/结构']
const filters = reactive({ variety: '', direction: 'all', factor: '', source: '', q: '', sort: 'importance', days: 30 })
const items = ref([])
const page = ref(1)
const hasMore = ref(false)
const loading = ref(false)
const drawerId = ref(null)
const varieties = ref([])
const sources = ref([])
const showMore = ref(false)
let searchTimer = null

async function load(reset = false) {
  loading.value = true
  if (reset) { page.value = 1; items.value = [] }
  try {
    const res = await api.feed({
      page: page.value, page_size: 20, variety: filters.variety || undefined,
      direction: filters.direction, factor: filters.factor || undefined,
      source: filters.source || undefined, q: filters.q || undefined,
      sort: filters.sort, days: filters.days,
    })
    items.value = reset ? res.items : items.value.concat(res.items)
    hasMore.value = res.has_more
  } finally {
    loading.value = false
  }
}

function loadMore() { page.value += 1; load(false) }
function changeDirection(d) { filters.direction = d; load(true) }
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(true), 400)
}

onMounted(async () => {
  load(true)
  try {
    const [vs, ss] = await Promise.all([api.varieties(), api.sources()])
    varieties.value = vs.filter((v) => v.is_active)
    sources.value = ss.sources.filter((s) => s.type !== 'market')
  } catch (e) { /* ignore */ }
})

watch(() => live.version, () => {
  if (live.lastEvent?.event === 'article_new' || live.lastEvent?.event === 'analysis_update') load(true)
})
</script>

<template>
  <div class="container">
    <div class="page-head">
      <div>
        <h1>信息流</h1>
        <div class="sub">点击任意一条查看原文、评分依据与人工修正</div>
      </div>
    </div>

    <div class="card">
      <div class="filters">
        <div class="seg">
          <button :class="{ active: filters.direction === 'all' }" @click="changeDirection('all')">全部</button>
          <button :class="{ active: filters.direction === 'bullish' }" @click="changeDirection('bullish')">利多</button>
          <button :class="{ active: filters.direction === 'bearish' }" @click="changeDirection('bearish')">利空</button>
        </div>
        <select v-model="filters.variety" class="select" @change="load(true)">
          <option value="">全部品种</option>
          <option v-for="v in varieties" :key="v.code" :value="v.code">{{ v.name }}</option>
        </select>
        <input v-model="filters.q" class="input search" placeholder="搜索标题 / 正文…" @input="onSearch" />
        <button class="btn btn-sm" @click="showMore = !showMore">{{ showMore ? '收起筛选' : '更多筛选' }}</button>
      </div>

      <div v-if="showMore" class="filters" style="border-top:1px solid var(--line)">
        <select v-model="filters.factor" class="select" @change="load(true)">
          <option value="">全部因子</option>
          <option v-for="f in FACTORS" :key="f" :value="f">{{ f }}</option>
        </select>
        <select v-model="filters.source" class="select" @change="load(true)">
          <option value="">全部来源</option>
          <option v-for="s in sources" :key="s.code" :value="s.name">{{ s.name }}</option>
        </select>
        <select v-model="filters.days" class="select" @change="load(true)">
          <option :value="1">近 1 天</option>
          <option :value="3">近 3 天</option>
          <option :value="7">近 7 天</option>
          <option :value="30">近 30 天</option>
        </select>
        <select v-model="filters.sort" class="select" @change="load(true)">
          <option value="importance">按重要性</option>
          <option value="time">按发布时间</option>
        </select>
      </div>

      <div class="feed-list">
        <ArticleCard v-for="a in items" :key="a.id" :article="a" @open="drawerId = $event" />
        <div v-if="loading" class="loading">加载中…</div>
        <div v-else-if="!items.length" class="empty">没有匹配的信息。调整筛选，或到「手工录入」添加一条。</div>
      </div>
      <div v-if="hasMore" style="padding:12px; text-align:center; border-top:1px solid var(--line)">
        <button class="btn btn-sm" :disabled="loading" @click="loadMore">加载更多</button>
      </div>
    </div>
  </div>

  <ArticleDrawer v-if="drawerId" :doc-id="drawerId" @close="drawerId = null" />
</template>
