<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api, fmtTime } from '../api'
import TrendChart from './TrendChart.vue'

const props = defineProps({ code: { type: String, required: true } })
const emit = defineEmits(['close'])

const variety = ref(null)
const trend = ref(null)
const loading = ref(true)
const err = ref('')
const days = ref(60)

async function load() {
  loading.value = true
  err.value = ''
  try {
    const [v, t] = await Promise.all([
      api.get(`/api/v1/varieties/${props.code}`),
      api.get(`/api/v1/varieties/${props.code}/trend?days=${days.value}`),
    ])
    variety.value = v
    trend.value = t
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.code, load)
watch(days, load)

const sentClass = computed(() => {
  const v = variety.value?.sentiment || 0
  if (v > 10) return 'pos'
  if (v < -10) return 'neg'
  return 'neu'
})

const dsFactors = computed(() => {
  const fw = variety.value?.daily_summary?.factor_weights || {}
  return Object.entries(fw)
    .sort((a, b) => b[1] - a[1])
    .map(([name, weight]) => ({ name, weight }))
})
</script>

<template>
  <div class="drawer-mask" @click.self="emit('close')">
    <aside class="drawer drawer-wide">
      <div class="drawer-head">
        <div>
          <h2>{{ variety?.name || props.code }} · 历史趋势</h2>
          <span class="hint" v-if="variety">{{ variety.sector }}</span>
        </div>
        <button class="btn btn-sm" @click="emit('close')">关闭</button>
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <div v-else-if="err" class="empty">加载失败：{{ err }}</div>
      <div v-else class="drawer-body">
        <div class="vt-summary">
          <div class="vt-big" :class="sentClass">
            <b>{{ variety.sentiment >= 0 ? '+' : '' }}{{ variety.sentiment.toFixed(1) }}</b>
            <span>情绪指数（近 7 天 importance 加权）</span>
          </div>
          <div class="vt-stats">
            <div><b>{{ variety.bullish_count ?? (trend?.series.reduce((a,b)=>a+b.bullish,0)) }}</b><span>利多资讯</span></div>
            <div><b>{{ variety.bearish_count ?? (trend?.series.reduce((a,b)=>a+b.bearish,0)) }}</b><span>利空资讯</span></div>
            <div><b>{{ variety.count ?? 0 }}</b><span>样本总量</span></div>
          </div>
        </div>

        <!-- 主力行情 -->
        <div v-if="variety.quote" class="vt-live">
          <span class="vl-price">{{ variety.quote.price }}</span>
          <span class="vl-pct" :class="variety.quote.change_pct >= 0 ? 'up' : 'down'">
            {{ variety.quote.change_pct > 0 ? '+' : '' }}{{ variety.quote.change_pct }}%
          </span>
          <span class="vl-meta">主力 · 强度 {{ variety.quote.strength }} · {{ fmtTime(variety.quote.quoted_at) }}</span>
        </div>

        <!-- DeepSeek 研判 -->
        <div v-if="variety.daily_summary" class="vt-ds" :class="'ds-' + variety.daily_summary.direction">
          <div class="vt-ds-head">
            <span class="vt-ds-tag" :class="'ds-' + variety.daily_summary.direction">
              DS 研判 · {{ variety.daily_summary.direction === 'bullish' ? '看多' :
                            variety.daily_summary.direction === 'bearish' ? '看空' : '中性' }}
            </span>
            <span class="vt-ds-num">{{ variety.daily_summary.sentiment_llm >= 0 ? '+' : '' }}{{ variety.daily_summary.sentiment_llm?.toFixed(1) }}</span>
          </div>
          <p class="vt-ds-sum">{{ variety.daily_summary.summary }}</p>
          <p v-if="variety.daily_summary.reasoning" class="vt-ds-reason">{{ variety.daily_summary.reasoning }}</p>
          <span class="vt-ds-foot">
            研判 {{ fmtTime(variety.daily_summary.updated_at) }} ·
            置信度 {{ (variety.daily_summary.confidence * 100).toFixed(0) }}% ·
            样本 {{ variety.daily_summary.article_count }} 条
          </span>
        </div>

        <div class="vt-chart-head">
          <h3>历史趋势</h3>
          <div class="seg">
            <button v-for="d in [7, 30, 60, 180]" :key="d"
                    :class="{ active: days === d }" @click="days = d">{{ d }} 天</button>
          </div>
        </div>
        <TrendChart :code="variety.code" :name="variety.name" :series="trend?.series || []" />

        <div v-if="variety.linkage" class="vt-linkage">
          <div class="vt-lk-head">
            <h4>外盘传导链</h4>
            <span class="vt-lk-signal" :class="variety.linkage.direction">
              {{ variety.linkage.direction === 'bullish' ? '偏多' :
                      variety.linkage.direction === 'bearish' ? '偏空' : '中性' }}
              {{ variety.linkage.signal > 0 ? '+' : '' }}{{ variety.linkage.signal }}
            </span>
          </div>
          <div class="vt-lk-row" v-for="c in variety.linkage.contributors" :key="c.code">
            <span class="lk-name">{{ c.name }}</span>
            <span :class="c.change_pct >= 0 ? 'up' : 'down'">
              {{ c.change_pct > 0 ? '+' : '' }}{{ c.change_pct }}%
            </span>
            <span class="muted">权重 {{ c.weight.toFixed(2) }}</span>
            <span class="lk-imp" :class="c.impact >= 0 ? 'up' : 'down'">
              {{ c.impact > 0 ? '+' : '' }}{{ c.impact }}
            </span>
          </div>
          <p class="vt-lk-tip">按经验权重把外盘涨跌幅折算成本品种的同向压力：正值偏多、负值偏空。</p>
        </div>

        <div v-if="variety.top_bullish?.length || variety.top_bearish?.length" class="vt-events">
          <div class="vt-col">
            <h4 class="pos">🔥 Top 利多</h4>
            <ul v-if="variety.top_bullish?.length" class="vt-list">
              <li v-for="b in variety.top_bullish" :key="b.doc_id">
                <a :href="`#/feed?variety=${variety.code}&direction=bullish`">{{ b.title }}</a>
                <span class="meta">imp {{ b.importance }} · {{ (b.published_at || '').slice(5, 16) }}</span>
              </li>
            </ul>
            <li v-else class="empty" style="font-size:12px">暂无</li>
          </div>
          <div class="vt-col">
            <h4 class="neg">❄️ Top 利空</h4>
            <ul v-if="variety.top_bearish?.length" class="vt-list">
              <li v-for="b in variety.top_bearish" :key="b.doc_id">
                <a :href="`#/feed?variety=${variety.code}&direction=bearish`">{{ b.title }}</a>
                <span class="meta">imp {{ b.importance }} · {{ (b.published_at || '').slice(5, 16) }}</span>
              </li>
            </ul>
            <li v-else class="empty" style="font-size:12px">暂无</li>
          </div>
        </div>

        <div v-if="dsFactors.length" class="vt-factors">
          <h4>DS 研判权重（含盘面动量）</h4>
          <div class="factor-tags">
            <span v-for="f in dsFactors" :key="f.name" class="factor-chip ds-chip"
                  :class="{ 'ds-chip-hot': f.name === '盘面动量' }">
              {{ f.name }} · {{ f.weight }}
            </span>
          </div>
        </div>

        <div v-if="variety.factors?.length" class="vt-factors">
          <h4>品种静态因子权重</h4>
          <div class="factor-tags">
            <span v-for="f in variety.factors" :key="f.name" class="factor-chip"
                  :style="{ background: (f.color || '#e2e8f0') + '22', borderColor: f.color || '#cbd5e1', color: f.color || '#475569' }">
              {{ f.name }} · {{ (f.weight * 10).toFixed(1) }}
            </span>
          </div>
        </div>

        <router-link :to="`/variety/${variety.code}`" class="btn vt-link" @click="emit('close')">
          进入品种页查看全部 →
        </router-link>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.drawer-wide { max-width: 760px; width: 92vw; }
.vt-summary { display: flex; gap: 16px; align-items: stretch; margin: 14px 0; }
.vt-big { flex: 0 0 210px; background: #f8fafc; border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; justify-content: center; border-left: 4px solid #94a3b8; }
.vt-big.pos { border-left-color: #ef4444; background: #fef2f2; }
.vt-big.neg { border-left-color: #10b981; background: #f0fdf4; }
.vt-big b { font-size: 34px; font-weight: 700; font-variant-numeric: tabular-nums; }
.vt-big.pos b { color: #dc2626; }
.vt-big.neg b { color: #059669; }
.vt-big span { font-size: 11px; color: #64748b; margin-top: 2px; }
.vt-stats { flex: 1; display: flex; gap: 12px; }
.vt-stats > div { flex: 1; background: #f8fafc; border-radius: 10px; padding: 12px; text-align: center; }
.vt-stats b { display: block; font-size: 22px; font-weight: 700; color: #1e293b; }
.vt-stats span { font-size: 11px; color: #64748b; }
.vt-chart-head { display: flex; justify-content: space-between; align-items: center; margin: 16px 0 6px; }
.vt-chart-head h3 { font-size: 14px; color: #1e293b; margin: 0; }
.seg { display: inline-flex; background: #f1f5f9; border-radius: 8px; padding: 2px; gap: 2px; }
.seg button { padding: 4px 10px; font-size: 12px; border: none; background: transparent; border-radius: 6px; color: #64748b; cursor: pointer; }
.seg button.active { background: #fff; color: #1e40af; box-shadow: 0 1px 2px rgba(0,0,0,.06); font-weight: 600; }
.vt-live { display: flex; align-items: baseline; gap: 10px; margin: 10px 0 2px; }
.vt-live .vl-price { font-size: 20px; font-weight: 700; color: #1e293b; font-variant-numeric: tabular-nums; }
.vt-live .vl-pct { font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; }
.vt-live .vl-pct.up { color: #dc2626; }
.vt-live .vl-pct.down { color: #16a34a; }
.vt-live .vl-meta { font-size: 11px; color: #94a3b8; }
.vt-ds { margin-top: 10px; border-radius: 10px; padding: 10px 12px; border: 1px solid #e2e8f0; background: #f8fafc; }
.vt-ds.ds-bullish { background: #fef2f2; border-color: #fecaca; }
.vt-ds.ds-bearish { background: #f0fdf4; border-color: #bbf7d0; }
.vt-ds-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.vt-ds-tag { font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 999px; background: #e2e8f0; color: #475569; }
.vt-ds-tag.ds-bullish { background: #fee2e2; color: #b91c1c; }
.vt-ds-tag.ds-bearish { background: #dcfce7; color: #166534; }
.vt-ds-num { font-size: 14px; font-weight: 700; color: #334155; font-variant-numeric: tabular-nums; }
.vt-ds-sum { font-size: 13px; color: #1e293b; margin: 0 0 4px; line-height: 1.5; }
.vt-ds-reason { font-size: 11.5px; color: #64748b; margin: 0 0 6px; line-height: 1.5; }
.vt-ds-foot { font-size: 10.5px; color: #94a3b8; }
.vt-linkage { margin-top: 14px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; }
.vt-lk-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.vt-lk-head h4 { font-size: 12px; color: #64748b; margin: 0; }
.vt-lk-signal { font-size: 12px; font-weight: 700; padding: 1px 8px; border-radius: 999px; }
.vt-lk-signal.bullish { background: #fee2e2; color: #b91c1c; }
.vt-lk-signal.bearish { background: #dcfce7; color: #166534; }
.vt-lk-signal.neutral { background: #e2e8f0; color: #475569; }
.vt-lk-row { display: flex; align-items: center; gap: 10px; font-size: 12px; padding: 3px 0; border-top: 1px dashed #e2e8f0; }
.vt-lk-row .lk-name { flex: 1; color: #1e293b; }
.vt-lk-row .up { color: #dc2626; font-variant-numeric: tabular-nums; }
.vt-lk-row .down { color: #16a34a; font-variant-numeric: tabular-nums; }
.vt-lk-row .lk-imp { font-weight: 700; font-variant-numeric: tabular-nums; min-width: 46px; text-align: right; }
.vt-lk-tip { font-size: 10.5px; color: #94a3b8; margin: 6px 0 0; }
.vt-events { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
.vt-col h4 { font-size: 13px; margin: 0 0 6px; }
.vt-col h4.pos { color: #dc2626; }
.vt-col h4.neg { color: #059669; }
.vt-list { list-style: none; padding: 0; margin: 0; }
.vt-list li { background: #f8fafc; border-radius: 8px; padding: 8px 10px; margin-bottom: 6px; font-size: 12px; }
.vt-list li a { color: #1e293b; text-decoration: none; display: block; line-height: 1.35; }
.vt-list li a:hover { color: #1e40af; }
.vt-list .meta { display: block; font-size: 10px; color: #94a3b8; margin-top: 2px; }
.vt-factors h4 { font-size: 12px; color: #64748b; margin: 14px 0 6px; }
.factor-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.factor-chip { padding: 4px 10px; border-radius: 999px; border: 1px solid; font-size: 11px; }
.ds-chip { background: #eff6ff; border-color: #bfdbfe; color: #1d4ed8; }
.ds-chip-hot { background: #fef3c7; border-color: #fcd34d; color: #b45309; font-weight: 700; }
.vt-link { display: block; text-align: center; margin-top: 16px; padding: 10px; }
</style>
