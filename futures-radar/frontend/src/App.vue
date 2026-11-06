<script setup>
import { onMounted, ref, watch } from 'vue'
import { api } from './api'
import { connectSSE, live, pushToast } from './store'
import ManualModal from './components/ManualModal.vue'

const meta = ref(null)
const showManual = ref(false)
const nav = [
  { to: '/', label: '今日总览' },
  { to: '/feed', label: '信息流' },
  { to: '/digest', label: '每日简报' },
  { to: '/sources', label: '数据源' },
]

onMounted(async () => {
  connectSSE()
  try { meta.value = await api.meta() } catch (e) { /* ignore */ }
})

watch(() => live.version, () => {
  if (live.lastEvent?.event === 'system') pushToast('首轮采集完成，数据已更新', 'info')
})
</script>

<template>
  <header class="header">
    <div class="header-inner">
      <router-link to="/" class="brand">
        <div class="brand-mark">FR</div>
        <div>Futures Radar<small>CZCE · 资讯研判工作台</small></div>
      </router-link>
      <nav class="nav">
        <router-link v-for="n in nav" :key="n.to" :to="n.to">{{ n.label }}</router-link>
      </nav>
      <div class="header-right">
        <span class="pill mode" :class="meta?.llm_available ? 'mode-deepseek' : 'mode-rule'">
          {{ meta?.llm_available ? `DeepSeek · ${meta.llm_model}` : '免费模式 · 规则引擎' }}
        </span>
        <span class="pill"><span class="dot" :class="live.connected ? 'on' : 'off'"></span>{{ live.connected ? '实时' : '连接中' }}</span>
        <button class="btn btn-ghost btn-sm" @click="showManual = true">+ 手工录入</button>
      </div>
    </div>
  </header>

  <router-view />

  <ManualModal v-if="showManual" @close="showManual = false" />
  <div class="toast-wrap">
    <div v-for="t in live.toasts" :key="t.id" class="toast" :class="t.type">{{ t.message }}</div>
  </div>
</template>
