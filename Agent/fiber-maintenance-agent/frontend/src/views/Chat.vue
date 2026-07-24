<template>
  <div style="display: flex; flex-direction: column; height: 100%">
    <!-- 消息区 -->
    <div ref="msgArea" style="flex: 1; overflow-y: auto; padding: 24px">
      <div v-for="(msg, i) in messages" :key="i"
           :style="{ textAlign: msg.role === 'user' ? 'right' : 'left', marginBottom: '12px' }">
        <el-tag v-if="msg.type === 'warning'" type="warning" style="margin-bottom: 4px">
          {{ msg.content }}
        </el-tag>
        <el-tag v-else-if="msg.type === 'subagent'" type="info" size="small" style="margin-bottom: 4px">
          🤖 [{{ msg.agent }}] {{ msg.content?.slice(0, 100) }}...
        </el-tag>
        <div v-else
             :style="{
               display: 'inline-block', maxWidth: '70%', padding: '10px 14px',
               borderRadius: '12px', textAlign: 'left',
               background: msg.role === 'user' ? '#1d3557' : '#f1f3f5',
               color: msg.role === 'user' ? '#fff' : '#333',
             }"
             v-html="renderMd(msg.content)">
        </div>
      </div>
      <div v-if="streaming" style="color: #999; padding: 8px">⏳ 思考中...</div>
    </div>

    <!-- 输入区 -->
    <div style="padding: 16px 24px; border-top: 1px solid #eee; display: flex; gap: 12px">
      <el-input v-model="input" placeholder="输入分析需求，如：分析光纤 F1001 的衰耗"
                @keyup.enter="send" :disabled="streaming" />
      <el-button type="primary" @click="send" :loading="streaming">发送</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { marked } from 'marked'

interface Msg { role: string; content: string; type?: string; agent?: string }

const messages = ref<Msg[]>([])
const input = ref('')
const streaming = ref(false)
const sessionId = ref(`s-${Math.random().toString(36).slice(2, 10)}`)
const msgArea = ref<HTMLElement>()

function renderMd(text: string) {
  return marked.parse(text || '', { async: false }) as string
}

function scrollBottom() {
  nextTick(() => { if (msgArea.value) msgArea.value.scrollTop = msgArea.value.scrollHeight })
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: text })
  streaming.value = true
  scrollBottom()

  // 占位 assistant 消息
  const aiIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '' })

  try {
    const resp = await fetch('/api/v1/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId.value, message: text }),
    })
    const reader = resp.body!.getReader()
    const decoder = new TextDecoder()
    let buf = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6)
        if (payload === '[DONE]') continue
        try {
          const ev = JSON.parse(payload)
          if (ev.type === 'token') {
            messages.value[aiIdx].content += ev.content
            scrollBottom()
          } else if (ev.type === 'warning') {
            messages.value.splice(aiIdx, 0, { role: 'system', content: ev.content, type: 'warning' })
          } else if (ev.type === 'subagent') {
            messages.value.splice(aiIdx, 0, { role: 'system', content: ev.content, type: 'subagent', agent: ev.agent })
          } else if (ev.type === 'error') {
            messages.value[aiIdx].content += `\n\n❌ ${ev.content}`
          }
        } catch { /* skip */ }
      }
    }
  } catch (e: any) {
    messages.value[aiIdx].content = `❌ 请求失败: ${e.message}`
  } finally {
    streaming.value = false
    scrollBottom()
  }
}
</script>