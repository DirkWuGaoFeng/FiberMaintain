<template>
  <div class="admin-container">
    <header class="admin-header">
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
          <h1>光纤维护服务系统</h1>
          <small>FIBER OPS · DEERFLOW 2.0 · FIBERHOME</small>
        </div>
      </div>
      <div class="nav-links">
        <a href="/" class="nav-link">返回首页</a>
      </div>
    </header>

    <main class="admin-main">
      <h2>📚 知识库管理</h2>

      <div class="panel hud" style="animation-delay: .02s">
        <div class="sec">上传文档</div>
        <div class="upload-form">
          <el-form inline>
            <el-form-item label="分类">
              <el-select v-model="uploadCategory" style="width: 200px">
                <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-upload :auto-upload="false" :on-change="onFileChange" :limit="1"
                         accept=".md,.txt,.pdf,.docx">
                <el-button>选择文件</el-button>
              </el-upload>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="upload" :loading="uploading">上传</el-button>
            </el-form-item>
          </el-form>
        </div>
      </div>

      <div class="panel hud" style="animation-delay: .08s">
        <div class="sec">文档列表
          <span class="r">
            <el-radio-group v-model="filterStatus" size="small" @change="loadDocs">
              <el-radio-button label="">全部</el-radio-button>
              <el-radio-button label="PENDING">待审核</el-radio-button>
              <el-radio-button label="ACTIVE">已入库</el-radio-button>
            </el-radio-group>
          </span>
        </div>
        <div class="docs-table">
          <el-table :data="docs" size="small">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="filename" label="文件名" />
            <el-table-column prop="category" label="分类" width="140" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="上传时间" width="180" />
            <el-table-column label="操作" width="240">
              <template #default="{ row }">
                <el-button v-if="row.status === 'PENDING'" size="small" type="success"
                           @click="review(row.id, 'approve')">通过</el-button>
                <el-button v-if="row.status === 'PENDING'" size="small" type="danger"
                           @click="review(row.id, 'reject')">驳回</el-button>
                <el-button v-if="row.status === 'APPROVED'" size="small" type="primary"
                           @click="ingest(row.id)">入库</el-button>
                <el-button v-if="['ACTIVE','APPROVED'].includes(row.status)" size="small"
                           @click="remove(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <div class="panel hud" style="animation-delay: .14s">
        <div class="sec">检索测试</div>
        <div class="search-section">
          <el-input v-model="searchQuery" placeholder="输入查询测试检索效果" @keyup.enter="search">
            <template #append>
              <el-button @click="search" :loading="searching">检索</el-button>
            </template>
          </el-input>
          <div v-if="searchResults.length" class="search-results">
            <el-collapse>
              <el-collapse-item v-for="(hit, i) in searchResults" :key="i"
                                :title="`[${hit.source}] 相关度: ${hit.score?.toFixed(3)}`">
                <pre>{{ hit.text }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const categories = [
  '01_设备技术手册', '02_维护操作规范', '03_告警处理指南',
  '04_历史故障案例', '05_衰耗阈值标准', '06_网元配置规范',
]
const uploadCategory = ref(categories[1])
const uploading = ref(false)
const selectedFile = ref<File | null>(null)
const docs = ref<any[]>([])
const filterStatus = ref('')
const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref<any[]>([])

function statusType(s: string) {
  const map: Record<string, string> = { PENDING: 'warning', APPROVED: 'primary', ACTIVE: 'success', REJECTED: 'danger', DELETED: 'info' }
  return map[s] || 'info'
}

function onFileChange(file: any) { selectedFile.value = file.raw }

async function upload() {
  if (!selectedFile.value) return ElMessage.warning('请选择文件')
  uploading.value = true
  const fd = new FormData()
  fd.append('file', selectedFile.value)
  fd.append('category', uploadCategory.value)
  try {
    await axios.post('/api/v1/knowledge/upload', fd, { headers: { 'X-User-Role': 'operator' } })
    ElMessage.success('上传成功，等待审核')
    loadDocs()
  } catch (e: any) { ElMessage.error(e.message) }
  finally { uploading.value = false }
}

async function loadDocs() {
  const { data } = await axios.get('/api/v1/knowledge/docs', { params: { status: filterStatus.value || undefined } })
  docs.value = data.docs
}

async function review(id: number, action: string) {
  await axios.post(`/api/v1/knowledge/docs/${id}/review`, { action }, { headers: { 'X-User-Role': 'admin' } })
  ElMessage.success(action === 'approve' ? '已通过' : '已驳回')
  loadDocs()
}

async function ingest(id: number) {
  await axios.post(`/api/v1/knowledge/docs/${id}/ingest`, {}, { headers: { 'X-User-Role': 'admin' } })
  ElMessage.success('入库完成')
  loadDocs()
}

async function remove(id: number) {
  await axios.delete(`/api/v1/knowledge/docs/${id}`, { headers: { 'X-User-Role': 'admin' } })
  ElMessage.success('已删除')
  loadDocs()
}

async function search() {
  if (!searchQuery.value.trim()) return
  searching.value = true
  try {
    const { data } = await axios.post('/api/v1/knowledge/search', { query: searchQuery.value, top_k: 5 })
    searchResults.value = data.hits
  } finally { searching.value = false }
}

onMounted(loadDocs)
</script>

<style scoped>
.admin-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg0);
}

.admin-header {
  height: 54px;
  flex: none;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 16px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, #0d1a2e, #0a1424);
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
}

.brand svg { width: 30px; height: 30px; }

.brand h1 { font-size: 16px; font-weight: 700; letter-spacing: .04em; color: var(--tx); }

.brand small {
  display: block;
  font-size: 10px;
  letter-spacing: .28em;
  color: var(--tx3);
  font-weight: 600;
}

.nav-links { margin-left: auto; }

.nav-link {
  color: var(--cyan);
  text-decoration: none;
  font-size: 13px;
  padding: 8px 16px;
  border-radius: 6px;
  transition: .2s;
}

.nav-link:hover { background: rgba(63, 208, 255, .1); }

.admin-main {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px;
}

.admin-main h2 {
  font-size: 20px;
  font-weight: 700;
  color: var(--tx);
  margin-bottom: 20px;
}

.upload-form, .docs-table, .search-section {
  padding: 16px;
}

.search-results { margin-top: 12px; }

.search-results pre {
  white-space: pre-wrap;
  font-size: 12px;
  color: var(--tx2);
}

:deep(.el-card) {
  background: linear-gradient(180deg, #10203a 0%, #0d1828 100%);
  border: 1px solid var(--line);
  border-radius: 7px;
}

:deep(.el-card__header) {
  background: transparent;
  border-bottom: 1px solid var(--line);
}

:deep(.el-card__body) { color: var(--tx); }

:deep(.el-table) {
  background: transparent;
  color: var(--tx);
}

:deep(.el-table th) {
  background: rgba(63, 208, 255, .05);
  color: var(--tx2);
  font-weight: 500;
}

:deep(.el-table td) { color: var(--tx); }

:deep(.el-table tr:hover > td) {
  background: rgba(63, 208, 255, .08);
}

:deep(.el-input__wrapper) {
  background: #0a1524;
  border-color: var(--line);
  box-shadow: none;
}

:deep(.el-input__wrapper:hover) { border-color: var(--cyan); }

:deep(.el-input__wrapper.is-focus) {
  border-color: var(--cyan);
  box-shadow: 0 0 0 3px rgba(63, 208, 255, .12);
}

:deep(.el-select .el-input__wrapper) {
  background: #0a1524;
  border-color: var(--line);
}

:deep(.el-select .el-input__wrapper:hover) { border-color: var(--cyan); }

:deep(.el-select .el-input__wrapper.is-focus) {
  border-color: var(--cyan);
  box-shadow: 0 0 0 3px rgba(63, 208, 255, .12);
}

:deep(.el-radio-button__inner) {
  background: transparent;
  border-color: var(--line);
  color: var(--tx2);
}

:deep(.el-radio-button__inner:hover) {
  background: rgba(63, 208, 255, .1);
  border-color: var(--cyan);
  color: var(--cyan);
}

:deep(.el-radio-button.is-active .el-radio-button__inner) {
  background: rgba(63, 208, 255, .16);
  border-color: var(--cyan);
  color: var(--cyan);
}

:deep(.el-collapse-item__header) {
  background: rgba(63, 208, 255, .05);
  color: var(--tx2);
}

:deep(.el-collapse-item__content) {
  background: transparent;
  color: var(--tx);
}

:deep(.el-tag) {
  background: rgba(63, 208, 255, .1);
  border-color: rgba(63, 208, 255, .3);
  color: var(--cyan);
}

:deep(.el-tag--success) {
  background: rgba(47, 214, 163, .1);
  border-color: rgba(47, 214, 163, .3);
  color: var(--green);
}

:deep(.el-tag--warning) {
  background: rgba(255, 178, 36, .1);
  border-color: rgba(255, 178, 36, .3);
  color: var(--amber);
}

:deep(.el-tag--danger) {
  background: rgba(255, 82, 87, .1);
  border-color: rgba(255, 82, 87, .3);
  color: var(--red);
}

:deep(.el-button) {
  background: rgba(79, 141, 255, .08);
  border-color: var(--line);
  color: var(--tx2);
}

:deep(.el-button:hover) {
  border-color: var(--cyan);
  color: var(--cyan);
}

:deep(.el-button--primary) {
  background: linear-gradient(180deg, rgba(63, 208, 255, .25), rgba(63, 208, 255, .08));
  border-color: rgba(63, 208, 255, .55);
  color: var(--cyan);
}

:deep(.el-button--primary:hover) {
  box-shadow: 0 0 18px rgba(63, 208, 255, .4);
}

:deep(.el-button--success) {
  background: rgba(47, 214, 163, .15);
  border-color: rgba(47, 214, 163, .4);
  color: var(--green);
}

:deep(.el-button--danger) {
  background: rgba(255, 82, 87, .15);
  border-color: rgba(255, 82, 87, .4);
  color: var(--red);
}
</style>
