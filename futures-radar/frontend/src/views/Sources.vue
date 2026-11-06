<script setup>
import { onMounted, ref } from 'vue'
import { api, fmtDateTime } from '../api'
import { pushToast } from '../store'

const sources = ref([])
const logs = ref([])
const running = ref('')
const loading = ref(true)

const TASKS = [
  ['jin10_flash', '金十快讯'], ['sina_rss', '新浪 RSS'], ['czce_announce', '郑商所公告'],
  ['oil', '原油行情'], ['fred', 'FRED 布伦特'], ['digest', '生成简报'],
]

async function load() {
  loading.value = true
  try {
    const res = await api.sources()
    sources.value = res.sources
    logs.value = res.logs
  } finally {
    loading.value = false
  }
}

async function run(task) {
  running.value = task
  try {
    const res = await api.runTask(task)
    pushToast(res.ok ? `${task} 执行完成` : `${task} 执行失败：${res.result?.error || ''}`.slice(0, 80), res.ok ? 'bull' : 'info')
  } catch (e) {
    pushToast(`执行失败：${e.message}`, 'info')
  } finally {
    running.value = ''
    load()
  }
}

async function toggle(s) {
  try {
    const res = await api.toggleSource(s.id)
    s.enabled = res.enabled
    pushToast(`${s.name} 已${res.enabled ? '启用' : '停用'}`, 'info')
  } catch (e) {
    pushToast(e.message, 'info')
  }
}

onMounted(load)
</script>

<template>
  <div class="container">
    <div class="page-head">
      <div>
        <h1>数据源与任务</h1>
        <div class="sub">采集失败会自动记录日志，不影响其它源。郑商所官网有瑞数反爬，返回 412 属预期。</div>
      </div>
      <button class="btn btn-sm" @click="load">刷新</button>
    </div>

    <div class="card">
      <div class="card-head"><h3>手动触发</h3><span class="tiny muted">用于调试或补采</span></div>
      <div class="card-body row wrap">
        <button v-for="[task, label] in TASKS" :key="task" class="btn btn-sm" :disabled="!!running" @click="run(task)">
          {{ running === task ? '执行中…' : label }}
        </button>
      </div>
    </div>

    <div class="card section">
      <div class="card-head"><h3>数据源</h3><span class="tiny muted">来源权重参与评分</span></div>
      <div style="overflow-x:auto">
        <table class="table">
          <thead>
            <tr><th>数据源</th><th>级别</th><th>权重</th><th>间隔</th><th>状态</th><th>最近运行</th><th>累计入库</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="s in sources" :key="s.id">
              <td>
                <div>{{ s.name }}</div>
                <div class="tiny muted">{{ s.code }}</div>
              </td>
              <td><span class="chip">{{ s.level }}</span></td>
              <td class="mono">{{ s.weight.toFixed(2) }}</td>
              <td class="mono">{{ s.interval_sec ? s.interval_sec + 's' : '手动' }}</td>
              <td>
                <span class="status-dot" :class="s.last_status === 'ok' ? 'ok' : s.last_status === 'failed' ? 'failed' : ''"></span>
                <span class="small" style="margin-left:4px">{{ s.last_status === 'ok' ? '正常' : s.last_status === 'failed' ? '失败' : s.enabled ? '待运行' : '停用' }}</span>
                <div v-if="s.last_error" class="tiny" style="color:var(--bull); max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" :title="s.last_error">{{ s.last_error }}</div>
              </td>
              <td class="small muted">{{ s.last_run_at ? fmtDateTime(s.last_run_at) : '—' }}</td>
              <td class="mono">{{ s.total_docs }}</td>
              <td>
                <button class="btn btn-sm" @click="toggle(s)">{{ s.enabled ? '停用' : '启用' }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card section">
      <div class="card-head"><h3>采集日志</h3><span class="tiny muted">最近 30 条</span></div>
      <div style="overflow-x:auto">
        <table class="table">
          <thead><tr><th>时间</th><th>数据源</th><th>状态</th><th>抓取</th><th>新增</th><th>耗时</th><th>错误</th></tr></thead>
          <tbody>
            <tr v-for="l in logs" :key="l.id">
              <td class="small muted">{{ fmtDateTime(l.created_at) }}</td>
              <td class="small">{{ l.source_code }}</td>
              <td><span class="badge" :class="l.status === 'ok' ? 'bear' : 'bull'">{{ l.status === 'ok' ? '成功' : l.status === 'failed' ? '失败' : l.status }}</span></td>
              <td class="mono">{{ l.fetched_count }}</td>
              <td class="mono">{{ l.new_count }}</td>
              <td class="mono">{{ l.duration_ms }}ms</td>
              <td class="tiny muted" style="max-width:320px">{{ l.error || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
