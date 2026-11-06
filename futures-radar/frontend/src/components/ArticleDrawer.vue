<script setup>
import { computed, ref, watch } from 'vue'
import { api, fmtDateTime } from '../api'
import { pushToast } from '../store'

const props = defineProps({ docId: { type: Number, required: true } })
const emit = defineEmits(['close'])

const detail = ref(null)
const loading = ref(false)
const saving = ref(false)
const form = ref({ label: 'adjust', direction: 'bullish', strength: 3, factor: '供给', note: '' })
const FACTORS = ['供给', '需求', '库存', '成本', '政策', '天气', '宏观', '资金/结构']

const a = computed(() => detail.value?.analysis || {})
const dirLabel = computed(() => ({ bullish: '利多', bearish: '利空', neutral: '中性' }[a.value.direction] || '中性'))
const dirClass = computed(() => ({ bullish: 'bull', bearish: 'bear', neutral: 'neutral' }[a.value.direction] || 'neutral'))

async function load() {
  loading.value = true
  try {
    detail.value = await api.article(props.docId)
    form.value.direction = a.value.direction || 'neutral'
    form.value.strength = a.value.strength || 3
    form.value.factor = a.value.factor || '供给'
  } catch (e) {
    pushToast(`加载失败：${e.message}`, 'info')
  } finally {
    loading.value = false
  }
}

watch(() => props.docId, load, { immediate: true })

async function submitFeedback() {
  saving.value = true
  try {
    const body = {
      label: form.value.label,
      note: form.value.note,
      direction: form.value.direction,
      strength: Number(form.value.strength),
      factor: form.value.factor,
    }
    detail.value = await api.feedback(props.docId, body)
    pushToast('人工修正已保存，排序已更新', 'bull')
  } catch (e) {
    pushToast(`保存失败：${e.message}`, 'info')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <aside class="drawer">
      <div class="drawer-head">
        <div style="flex:1">
          <div class="row wrap" style="margin-bottom:6px">
            <span v-for="c in detail?.matched_varieties || []" :key="c" class="chip variety">{{ c }}</span>
            <span class="badge" :class="dirClass">{{ dirLabel }}</span>
            <span v-if="a.status === 'quick'" class="badge gray">研判中</span>
            <span v-else class="badge gray">{{ a.model === 'demo-seed' ? '示例数据' : a.model === 'rule-engine' ? '规则引擎' : a.model }}</span>
          </div>
          <div class="drawer-title">{{ detail?.title || '加载中…' }}</div>
          <div class="small muted" style="margin-top:6px">
            {{ detail?.source_name }} · {{ fmtDateTime(detail?.published_at) }}
            <span v-if="detail?.is_manual"> · 手工录入</span>
          </div>
        </div>
        <button class="close-x" @click="emit('close')">✕</button>
      </div>

      <div class="drawer-body">
        <div v-if="loading" class="loading">加载中…</div>
        <template v-else-if="detail">
          <div class="row" style="justify-content:space-between; margin-bottom:14px">
            <div>
              <div class="tiny muted">重要性</div>
              <div class="score-big" :class="dirClass">{{ Number(detail.importance || 0).toFixed(2) }}</div>
            </div>
            <div class="score-grid">
              <div class="score-cell"><div class="k">方向强度</div><div class="v">{{ a.strength }} / 5</div></div>
              <div class="score-cell"><div class="k">置信度</div><div class="v">{{ (Number(a.confidence || 0) * 100).toFixed(0) }}%</div></div>
              <div class="score-cell"><div class="k">因子</div><div class="v">{{ a.factor }}</div></div>
              <div class="score-cell"><div class="k">期限</div><div class="v">{{ a.horizon }}</div></div>
            </div>
          </div>

          <div class="section-head" style="margin:0 0 8px"><h2 style="font-size:13px">研判结论</h2></div>
          <div class="content-box" style="background:#fff; border-color:var(--line)">{{ a.summary || '—' }}</div>
          <div v-if="a.evidence" class="evidence"><strong>原文依据：</strong>{{ a.evidence }}</div>
          <div v-if="a.reasoning" class="small muted" style="margin-top:10px">影响逻辑：{{ a.reasoning }}</div>

          <div class="divider"></div>
          <div class="row" style="justify-content:space-between; margin-bottom:8px">
            <h3 style="font-size:13px">品种评分</h3>
            <span class="tiny muted">S = 方向 × 强度 × 置信度 × 来源权重 × 新鲜度 × 新颖度</span>
          </div>
          <table class="table">
            <thead><tr><th>品种</th><th>方向</th><th>因子</th><th>得分</th><th>重要性</th></tr></thead>
            <tbody>
              <tr v-for="s in a.scores || []" :key="s.id">
                <td><span class="chip variety">{{ s.variety_code }}</span></td>
                <td><span class="badge" :class="s.direction === 'bullish' ? 'bull' : s.direction === 'bearish' ? 'bear' : 'neutral'">
                  {{ s.direction === 'bullish' ? '利多' : s.direction === 'bearish' ? '利空' : '中性' }}</span></td>
                <td>{{ s.factor }}</td>
                <td class="mono">{{ Number(s.score).toFixed(3) }}</td>
                <td class="mono">{{ Number(s.importance).toFixed(2) }}</td>
              </tr>
              <tr v-if="!(a.scores || []).length"><td colspan="5" class="muted">暂无评分</td></tr>
            </tbody>
          </table>

          <div class="divider"></div>
          <h3 style="font-size:13px; margin-bottom:8px">原文快照</h3>
          <div class="content-box">{{ detail.content }}</div>
          <div v-if="detail.url" class="small" style="margin-top:8px">
            <a :href="detail.url" target="_blank" rel="noreferrer" style="color:var(--brand)">查看原文 ↗</a>
          </div>

          <div class="divider"></div>
          <h3 style="font-size:13px; margin-bottom:8px">人工修正</h3>
          <div class="feedback-form">
            <div class="row">
              <select v-model="form.direction" class="select">
                <option value="bullish">利多</option>
                <option value="bearish">利空</option>
                <option value="neutral">中性</option>
              </select>
              <select v-model="form.strength" class="select">
                <option v-for="n in 5" :key="n" :value="n">强度 {{ n }}</option>
              </select>
              <select v-model="form.factor" class="select">
                <option v-for="f in FACTORS" :key="f" :value="f">{{ f }}</option>
              </select>
              <select v-model="form.label" class="select">
                <option value="adjust">修正</option>
                <option value="correct">判断正确</option>
                <option value="wrong">判断有误</option>
              </select>
            </div>
            <input v-model="form.note" class="input" placeholder="备注（可选）" />
            <div class="row">
              <button class="btn btn-primary btn-sm" :disabled="saving" @click="submitFeedback">
                {{ saving ? '保存中…' : '保存修正' }}
              </button>
              <span class="tiny muted">修正后立即重算评分与排序</span>
            </div>
          </div>

          <div v-if="(detail.feedback || []).length" class="section">
            <h3 style="font-size:13px; margin-bottom:6px">修正记录</h3>
            <div v-for="f in detail.feedback" :key="f.id" class="small muted" style="margin-bottom:4px">
              {{ fmtDateTime(f.created_at) }} · {{ f.label }} · {{ f.note || '无备注' }}
            </div>
          </div>
        </template>
      </div>
    </aside>
  </div>
</template>
