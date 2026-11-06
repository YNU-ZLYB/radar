<script setup>
import { ref } from 'vue'
import { api } from '../api'
import { pushToast } from '../store'

const emit = defineEmits(['close'])
const title = ref('')
const content = ref('')
const url = ref('')
const saving = ref(false)

async function submit() {
  if (title.value.trim().length < 2) {
    pushToast('标题至少 2 个字', 'info')
    return
  }
  saving.value = true
  try {
    await api.manual({ title: title.value, content: content.value, url: url.value })
    pushToast('已录入，正在规则初判并推送', 'bull')
    emit('close')
  } catch (e) {
    pushToast(`录入失败：${e.message}`, 'info')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')"></div>
  <div class="modal">
    <h3>手工录入资讯</h3>
    <div class="small muted">适合复制微信群/付费终端里的消息，系统会自动识别品种并给出多空初判。</div>
    <div class="field">
      <label>标题</label>
      <input v-model="title" placeholder="例：伊朗两套甲醇装置计划停车检修" />
    </div>
    <div class="field">
      <label>正文</label>
      <textarea v-model="content" placeholder="粘贴原文内容，越完整研判越准"></textarea>
    </div>
    <div class="field">
      <label>原文链接（可选）</label>
      <input v-model="url" placeholder="https://…" />
    </div>
    <div class="row" style="justify-content:flex-end; margin-top:16px">
      <button class="btn" @click="emit('close')">取消</button>
      <button class="btn btn-primary" :disabled="saving" @click="submit">{{ saving ? '提交中…' : '提交录入' }}</button>
    </div>
  </div>
</template>
