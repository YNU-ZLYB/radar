<script setup>
import { computed } from 'vue'
import { fmtTime } from '../api'
import HighlightText from './HighlightText.vue'

const props = defineProps({ article: { type: Object, required: true } })
defineEmits(['open'])

const a = computed(() => props.article.analysis || {})
const pv = computed(() => props.article.primary_variety
  || { code: (props.article.matched_varieties || [])[0] || '—', name: '—' })
const dir = computed(() => props.article.direction || a.value.direction || 'neutral')
const dirLabel = computed(() => ({ bullish: '利多', bearish: '利空', neutral: '中性' }[dir.value] || '中性'))
const dirClass = computed(() => ({ bullish: 'bull', bearish: 'bear', neutral: 'neutral' }[dir.value] || 'neutral'))
</script>

<template>
  <div class="feed-item" @click="$emit('open', article.id)">
    <div class="feed-rail">
      <div class="rail-name">{{ pv.name }}</div>
      <div class="rail-code">{{ pv.code }}</div>
    </div>
    <div class="feed-main">
      <div class="feed-title"><HighlightText :text="article.title" /></div>
      <div class="feed-meta">
        <span class="chip">{{ a.factor || '—' }}</span>
        <span class="muted">{{ fmtTime(article.published_at) }}</span>
        <span class="muted">· {{ article.source_name }}</span>
        <span v-if="a.status === 'quick'" class="badge gray">研判中</span>
        <span v-else-if="a.model === 'demo-seed'" class="badge gray">示例</span>
      </div>
    </div>
    <div class="feed-side">
      <span class="side-dir" :class="dirClass">{{ dirLabel }}</span>
      <span class="side-imp">{{ Number(article.importance || 0).toFixed(1) }}</span>
    </div>
  </div>
</template>
