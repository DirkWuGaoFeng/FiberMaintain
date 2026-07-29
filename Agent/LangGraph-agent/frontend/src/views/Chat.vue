<template>
  <div class="chat-page">
    <header>
      <div class="brand">
        <svg viewBox="0 0 32 32" fill="none">
          <path d="M3 22 C11 22 11 10 19 10 H29" stroke="#3fd0ff" stroke-width="1.8"/>
          <path d="M3 16 H29" stroke="#4f8dff" stroke-width="1.8"/>
          <path d="M3 10 C11 10 11 22 19 22 H29" stroke="#2fd6a3" stroke-width="1.8"/>
          <circle cx="28" cy="16" r="2.6" fill="#3fd0ff">
            <animate attributeName="opacity" values="1;.3;1" dur="1.6s" repeatCount="indefinite"/>
          </circle>
        </svg>
        <div>
          <h1>智能对话</h1>
          <small>LANGGRAPH AGENT · CHAT</small>
        </div>
      </div>
      <router-link to="/" class="pill back-link">← 返回主面板</router-link>
    </header>

    <div class="chat-container">
      <div class="chat-panel">
        <div class="chat-head">
          <span>🤖 Lead Agent</span>
          <div class="mw">
            <span>AuthCB</span><span>RateLimitCB</span>
            <span>TracingCB</span><span>RAGInjectionCB</span>
          </div>
        </div>
        <div ref="chatlog" class="chatlog">
          <div v-for="msg in messages" :key="msg.id" :class="msg.type">
            <div v-if="msg.type === 'ubub'" class="wx-user">
              <div class="wx-bubble user-bubble">{{ msg.content }}</div>
              <div class="wx-avatar user-ava">我</div>
            </div>
            <div v-else-if="msg.type === 'amsg'" class="wx-ai">
              <div class="wx-avatar ai-ava">AI</div>
              <div class="wx-bubble ai-bubble">
                <div v-if="msg.thought && msg.thought.length" class="fold think">
                  <div class="fhead" @click="msg.thoughtOpen = !msg.thoughtOpen">
                    <span class="chev">▼</span>🤔 思考过程
                  </div>
                  <div class="fbody" v-show="msg.thoughtOpen">
                    <div v-for="(step, idx) in msg.thought" :key="idx" class="tstep">{{ step }}</div>
                  </div>
                </div>
                <div v-if="msg.tools && msg.tools.length" class="fold tool">
                  <div class="fhead" @click="msg.toolsOpen = !msg.toolsOpen">
                    <span class="chev">▼</span>🔧 工具调用 · {{ msg.tools.length }} 次
                  </div>
                  <div class="fbody" v-show="msg.toolsOpen">
                    <div v-for="(tool, idx) in msg.tools" :key="idx" class="trow">
                      <span class="ttag">{{ tool.tag.toUpperCase() }}</span>
                      <span class="tname">{{ tool.name }}</span>
                      <span class="tnote">{{ tool.note }}</span>
                    </div>
                  </div>
                </div>
                <div v-if="msg.report && msg.report.length" class="wx-extra">
                  <div v-for="(line, idx) in msg.report" :key="idx" class="wx-tag" :class="line.c">{{ line.t }}</div>
                </div>
                <div v-if="msg.rawMd" class="wx-md" v-html="renderMd(msg.rawMd)"></div>
                <div v-if="msg.done" class="wx-done">{{ msg.done }}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="inrow">
          <input v-model="inputText" @keyup.enter="sendMessage"
            placeholder="输入自然语言指令…" autocomplete="off">
          <button class="send" :class="{ glow: sending }" @click="sendMessage">发送</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { sendChatMessage } from '../api/index.js'
import { marked } from 'marked'

marked.setOptions({ breaks: true, gfm: true })
function renderMd(text) {
  if (!text) return ''
  try { return marked.parse(text) } catch { return text.replace(/</g, '&lt;') }
}

const messages = ref([])
const inputText = ref('')
const sending = ref(false)
const chatlog = ref(null)

function scrollToBottom() {
  setTimeout(() => { if (chatlog.value) chatlog.value.scrollTop = chatlog.value.scrollHeight }, 50)
}

async function sendMessage() {
  if (!inputText.value.trim() || sending.value) return
  sending.value = true
  const userMsg = { id: Date.now(), type: 'ubub', content: inputText.value }
  messages.value.push(userMsg); inputText.value = ''; scrollToBottom()
  const aiMsg = { id: Date.now() + 1, type: 'amsg', thoughtOpen: true, toolsOpen: false, thought: [], tools: [], rawMd: '', report: [], done: '' }
  messages.value.push(aiMsg); scrollToBottom()
  try {
    await sendChatMessage(userMsg.content, (event) => {
      if (event.type === 'thought') aiMsg.thought.push(event.content)
      else if (event.type === 'token') aiMsg.rawMd += event.content
      else if (event.type === 'tool_call') aiMsg.tools.push({ tag: event.tool || 'tool', name: event.tool || 'unknown', note: JSON.stringify(event.args || {}).slice(0, 120) })
      else if (event.type === 'tool_result') { const c = typeof event.content === 'string' ? event.content : JSON.stringify(event.content); aiMsg.report.push({ c: 'tool', t: `[${event.tool}] ${c.slice(0, 300)}` }) }
      else if (event.type === 'warning') aiMsg.report.push({ c: 'warn', t: event.content })
      else if (event.type === 'error') aiMsg.report.push({ c: 'err', t: event.content })
      else if (event.type === 'done') aiMsg.done = `✅ 完成 (${event.elapsed_ms || 0}ms)`
      else if (event.type === 'message') aiMsg.rawMd += (event.content || '')
      scrollToBottom()
    })
    if (!aiMsg.done) aiMsg.done = '✅ 完成'
  } catch (e) { aiMsg.rawMd += '\n❌ 服务暂时不可用，请稍后重试'; aiMsg.done = '❌ 失败' }
  sending.value = false
}
</script>

<style scoped>
.chat-page { height: 100vh; display: flex; flex-direction: column; background: var(--bg0); }
header { height: 54px; flex: none; display: flex; align-items: center; gap: 16px; padding: 0 16px; border-bottom: 1px solid var(--line); background: linear-gradient(180deg, #0d1a2e, #0a1424); }
.brand { display: flex; align-items: center; gap: 11px; }
.brand svg { width: 30px; height: 30px; }
.brand h1 { font-size: 16px; font-weight: 700; letter-spacing: .04em; }
.brand small { display: block; font-family: var(--disp); font-size: 10px; letter-spacing: .28em; color: var(--tx3); font-weight: 600; }
.back-link { margin-left: auto; cursor: pointer; color: var(--cyan); border-color: rgba(63,208,255,.4); background: rgba(63,208,255,.08); text-decoration: none; transition: .2s; }
.back-link:hover { background: rgba(63,208,255,.18); }
.chat-container { flex: 1; min-height: 0; display: flex; padding: 16px; }
.chat-panel { flex: 1; display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }
.chat-head { flex: none; display: flex; align-items: center; gap: 10px; padding: 9px 14px; border-bottom: 1px solid var(--line); font-size: 12px; color: var(--tx2); }
.chat-head .mw { margin-left: auto; display: flex; gap: 5px; flex-wrap: wrap; }
.chat-head .mw span { font-size: 9.5px; font-family: var(--mono); color: var(--tx3); border: 1px solid var(--line); padding: 1px 6px; border-radius: 3px; }
.chatlog { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 18px; display: flex; flex-direction: column; gap: 14px; scroll-behavior: smooth; }
.wx-user, .wx-ai { display: flex; align-items: flex-start; gap: 10px; animation: rise .35s both; }
.wx-user { justify-content: flex-end; }
.wx-ai { justify-content: flex-start; }
.wx-avatar { flex: none; width: 36px; height: 36px; border-radius: 6px; display: grid; place-items: center; font-size: 12px; font-weight: 700; }
.user-ava { background: linear-gradient(145deg, #1a6b3a, #0f4424); border: 1px solid rgba(47, 214, 163, .4); color: var(--green); }
.ai-ava { background: linear-gradient(145deg, #123152, #0c1e36); border: 1px solid #1e3554; color: var(--cyan); }
.wx-bubble { max-width: 72%; min-width: 80px; padding: 12px 16px; border-radius: 10px; font-size: 13.5px; line-height: 1.7; word-break: break-word; display: flex; flex-direction: column; gap: 8px; }
.user-bubble { background: linear-gradient(180deg, rgba(63, 208, 255, .18), rgba(63, 208, 255, .08)); border: 1px solid rgba(63, 208, 255, .35); border-radius: 10px 10px 2px 10px; color: var(--tx); }
.ai-bubble { background: linear-gradient(180deg, #111f35, #0d1829); border: 1px solid #1e3554; border-radius: 10px 10px 10px 2px; color: #d0dfef; }
.wx-md { font-size: 13.5px; line-height: 1.75; color: #d0dfef; }
.wx-md :deep(h1), .wx-md :deep(h2), .wx-md :deep(h3) { color: #fff; margin: 10px 0 6px; }
.wx-md :deep(code) { font-family: var(--mono); font-size: 12px; color: var(--cyan); background: rgba(63, 208, 255, .1); padding: 1px 5px; border-radius: 3px; }
.wx-md :deep(pre) { background: #0a1524; border: 1px solid #1c3149; border-radius: 6px; padding: 10px 12px; overflow-x: auto; }
.wx-md :deep(pre code) { background: none; padding: 0; color: #c9d9ef; }
.wx-extra { display: flex; flex-direction: column; gap: 4px; }
.wx-tag { font-size: 11.5px; padding: 4px 8px; border-radius: 4px; font-family: var(--mono); word-break: break-all; }
.wx-tag.tool { background: rgba(79, 141, 255, .1); color: var(--blue); border: 1px solid rgba(79, 141, 255, .25); }
.wx-tag.warn { background: rgba(255, 178, 36, .1); color: var(--amber); border: 1px solid rgba(255, 178, 36, .25); }
.wx-tag.err { background: rgba(255, 82, 87, .1); color: var(--red); border: 1px solid rgba(255, 82, 87, .25); }
.wx-done { font-size: 11px; color: var(--green); font-family: var(--mono); }
.fold { border: 1px solid var(--line); border-radius: 6px; background: rgba(9, 17, 30, .6); overflow: hidden; }
.fold > .fhead { display: flex; align-items: center; gap: 8px; padding: 7px 11px; cursor: pointer; user-select: none; font-size: 11.5px; color: var(--tx2); }
.fold.think { border-left: 2px solid var(--cyan); }
.fold.tool { border-left: 2px solid var(--blue); }
.fbody { padding: 4px 11px 9px 26px; }
.tstep { font-size: 12px; color: var(--tx2); padding: 3px 0; }
.trow { display: flex; align-items: center; gap: 8px; padding: 3.5px 0; font-size: 11.5px; }
.ttag { font-family: var(--mono); font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 3px; color: var(--cyan); background: rgba(63, 208, 255, .13); border: 1px solid rgba(63, 208, 255, .35); }
.tname { font-family: var(--mono); color: var(--tx2); }
.tnote { font-size: 10.5px; color: var(--tx3); }
.inrow { flex: none; display: flex; gap: 10px; padding: 10px 14px 14px; border-top: 1px solid var(--line); }
.inrow input { flex: 1; background: #0a1524; border: 1px solid var(--line); border-radius: 6px; color: var(--tx); padding: 10px 13px; font-size: 13px; font-family: inherit; outline: none; transition: .2s; }
.inrow input:focus { border-color: var(--cyan); box-shadow: 0 0 0 3px rgba(63, 208, 255, .12); }
.inrow .send { padding: 0 22px; border-radius: 6px; border: 1px solid rgba(63, 208, 255, .55); cursor: pointer; background: linear-gradient(180deg, rgba(63, 208, 255, .25), rgba(63, 208, 255, .08)); color: var(--cyan); font-weight: 700; font-size: 13px; letter-spacing: .14em; transition: .2s; }
.inrow .send:hover { box-shadow: 0 0 18px rgba(63, 208, 255, .4); }
.inrow .send.glow { animation: sendg 1s infinite; }
</style>
