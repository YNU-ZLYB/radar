<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { pushToast } from '../store'
import SentimentBar from '../components/SentimentBar.vue'
import HighlightText from '../components/HighlightText.vue'

const digests = ref([])
const active = ref(null)
const generating = ref(false)
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    digests.value = await api.digestList()
    if (digests.value.length && !active.value) active.value = digests.value[0]
  } finally {
    loading.value = false
  }
}

async function generate() {
  generating.value = true
  try {
    const res = await api.digestGenerate()
    pushToast('今日简报已生成', 'bull')
    digests.value = await api.digestList()
    active.value = digests.value.find((d) => d.date === res.date) || digests.value[0]
  } catch (e) {
    pushToast(`生成失败：${e.message}`, 'info')
  } finally {
    generating.value = false
  }
}

async function download() {
  if (!active.value) return
  const res = await fetch(`/api/v1/digests/${active.value.date}/markdown`)
  const text = await res.text()
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `futures-radar-${active.value.date}.md`
  a.click()
  URL.revokeObjectURL(a.href)
}

// 简报 markdown 由后端保存；列表接口返回 payload，预览使用 payload 重新组织简化文本
function renderPreview(d) {
  const lines = [`# 郑商所期货资讯简报 · ${d.date}`, '']
  const oil = (d.payload?.oil || []).filter((q) => q.price)
  if (oil.length) lines.push('**原油参考**：' + oil.map((q) => `${q.name} ${q.price}（${q.change_pct > 0 ? '+' : ''}${q.change_pct}%）`).join(' / '), '')
  for (const g of d.payload?.varieties || []) {
    lines.push(`## ${g.name} ${g.code}（情绪 ${g.sentiment > 0 ? '+' : ''}${g.sentiment}｜${g.count} 条）`)
    for (const [label, key] of [['利多', 'bullish'], ['利空', 'bearish']]) {
      lines.push(`### ${label} Top ${g[key].length}`)
      if (!g[key].length) lines.push('- 暂无')
      for (const it of g[key]) lines.push(`- **${it.title}**（重要性 ${it.importance}｜${it.factor}｜${it.source_name}）\n  - ${it.summary || '—'}`)
    }
    lines.push('')
  }
  return lines.join('\n')
}

onMounted(load)
const varieties = computed(() => active.value?.payload?.varieties || [])
</script>

<template>
  <div class="container">
    <div class="page-head">
      <div>
        <h1>每日简报</h1>
        <div class="sub">按品种分组的利多/利空 Top，支持导出 Markdown 存档。</div>
      </div>
      <button class="btn btn-primary" :disabled="generating" @click="generate">{{ generating ? '生成中…' : '生成今日简报' }}</button>
    </div>

    <section class="card">
        <div class="card-head">
          <h3>{{ active?.date || '暂无简报' }}</h3>
          <div class="row">
            <button class="btn btn-sm" :disabled="!active" @click="download">导出 Markdown</button>
          </div>
        </div>
        <div class="card-body">
          <div class="tabs" style="margin-bottom:14px; flex-wrap:wrap">
            <span v-for="d in digests" :key="d.date" class="tab" :class="{ active: active?.date === d.date }" @click="active = d">{{ d.date }}</span>
          </div>

          <div v-if="loading" class="loading">加载中…</div>
          <div v-else-if="!active" class="empty">
            还没有简报。点击右上角「生成今日简报」，系统会汇总当日入库资讯。
          </div>
          <template v-else>
            <div v-for="g in varieties" :key="g.code" class="digest-group">
              <div class="digest-group-head">
                <div class="row"><strong>{{ g.name }}</strong><span class="chip variety">{{ g.code }}</span></div>
                <div style="width:150px"><SentimentBar :value="g.sentiment" /></div>
              </div>
              <div class="digest-group-body">
                <div v-for="[label, key] in [['利多', 'bullish'], ['利空', 'bearish']]" :key="key">
                  <div class="tiny" :style="{ color: key === 'bullish' ? 'var(--bull)' : 'var(--bear)', margin: '4px 0' }">{{ label }} Top {{ g[key].length }}</div>
                  <div v-if="!g[key].length" class="tiny muted">暂无</div>
                  <div v-for="it in g[key]" :key="it.doc_id" class="mini-item" style="padding:3px 0">
                    <span class="chip" :class="key === 'bullish' ? 'bull' : 'bear'" style="background:transparent">{{ Number(it.importance).toFixed(2) }}</span>
                    <span class="t digest-title" style="white-space:normal"><HighlightText :text="it.title" /></span>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
    </section>

    <details class="card details-card">
      <summary><span>Markdown 预览</span></summary>
      <div style="padding: 0 18px 18px">
        <pre v-if="active" class="md-box">{{ renderPreview(active) }}</pre>
        <div v-else class="empty">生成后在此预览</div>
      </div>
    </details>
  </div>
</template>
