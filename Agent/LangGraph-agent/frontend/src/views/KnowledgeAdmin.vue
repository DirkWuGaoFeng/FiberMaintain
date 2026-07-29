<template>
  <div class="admin-container">
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
          <h1>RAG 知识库管理</h1>
          <small>LANGGRAPH AGENT · KNOWLEDGE ADMIN</small>
        </div>
      </div>
      <router-link to="/" class="pill back-link">← 返回主面板</router-link>
    </header>

    <div class="content">
      <div class="panel upload-panel">
        <div class="sec">上传文档</div>
        <el-form :model="uploadForm" label-width="80px">
          <el-form-item label="文档标题">
            <el-input v-model="uploadForm.title" placeholder="请输入文档标题"/>
          </el-form-item>
          <el-form-item label="文档类型">
            <el-select v-model="uploadForm.docType" placeholder="选择文档类型">
              <el-option label="技术规范" value="spec"/>
              <el-option label="故障案例" value="case"/>
              <el-option label="操作手册" value="manual"/>
              <el-option label="其他" value="other"/>
            </el-select>
          </el-form-item>
          <el-form-item label="选择文件">
            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :on-change="handleFileChange"
              :limit="1"
              accept=".md,.txt,.pdf"
            >
              <el-button type="primary">选择文件</el-button>
              <template #tip>
                <div class="el-upload__tip">支持 .md / .txt / .pdf 格式</div>
              </template>
            </el-upload>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="handleUpload" :loading="uploading">上传</el-button>
          </el-form-item>
        </el-form>
      </div>

      <div class="panel list-panel">
        <div class="sec">文档列表
          <div class="filter-tabs">
            <button :class="{ on: filter === 'all' }" @click="filter = 'all'">全部</button>
            <button :class="{ on: filter === 'pending' }" @click="filter = 'pending'">待审核</button>
            <button :class="{ on: filter === 'approved' }" @click="filter = 'approved'">已通过</button>
            <button :class="{ on: filter === 'rejected' }" @click="filter = 'rejected'">已拒绝</button>
          </div>
        </div>
        <el-table :data="filteredDocs" style="width: 100%">
          <el-table-column prop="title" label="标题" width="200"/>
          <el-table-column prop="docType" label="类型" width="100">
            <template #default="{ row }">
              <el-tag size="small">{{ typeMap[row.docType] || row.docType }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ statusMap[row.status] || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="uploadedAt" label="上传时间" width="180">
            <template #default="{ row }">
              {{ new Date(row.uploadedAt).toLocaleString() }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button v-if="row.status === 'pending'" type="success" size="small" @click="approveDoc(row.id)">通过</el-button>
              <el-button v-if="row.status === 'pending'" type="danger" size="small" @click="rejectDoc(row.id)">拒绝</el-button>
              <el-button type="danger" size="small" @click="deleteDoc(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { uploadKbDoc, getKbDocs, reviewKbDoc, deleteKbDoc } from '../api/index.js'

const uploadForm = ref({ title: '', docType: 'spec' })
const uploadRef = ref(null)
const selectedFile = ref(null)
const uploading = ref(false)
const docs = ref([])
const filter = ref('all')

const typeMap = { spec: '技术规范', case: '故障案例', manual: '操作手册', other: '其他' }
const statusMap = { pending: '待审核', approved: '已通过', rejected: '已拒绝' }
const statusType = (s) => ({ pending: 'warning', approved: 'success', rejected: 'danger' }[s] || 'info')

const filteredDocs = computed(() => {
  if (filter.value === 'all') return docs.value
  return docs.value.filter(d => d.status === filter.value)
})

function handleFileChange(file) { selectedFile.value = file.raw }

async function handleUpload() {
  if (!uploadForm.value.title || !selectedFile.value) {
    ElMessage.warning('请填写标题并选择文件'); return
  }
  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    formData.append('title', uploadForm.value.title)
    formData.append('docType', uploadForm.value.docType)
    await uploadKbDoc(formData)
    ElMessage.success('上传成功')
    uploadForm.value = { title: '', docType: 'spec' }; selectedFile.value = null
    uploadRef.value?.clearFiles()
    fetchDocs()
  } catch (e) { ElMessage.error('上传失败: ' + (e.message || '未知错误')) }
  uploading.value = false
}

async function fetchDocs() {
  try { const { data } = await getKbDocs(); docs.value = data.docs || [] } catch (e) { console.error(e) }
}

async function approveDoc(id) {
  try { await reviewKbDoc(id, { status: 'approved' }); ElMessage.success('已通过'); fetchDocs() }
  catch (e) { ElMessage.error('操作失败') }
}

async function rejectDoc(id) {
  try { await reviewKbDoc(id, { status: 'rejected' }); ElMessage.success('已拒绝'); fetchDocs() }
  catch (e) { ElMessage.error('操作失败') }
}

async function deleteDoc(id) {
  try {
    await ElMessageBox.confirm('确认删除该文档？', '提示', { type: 'warning' })
    await deleteKbDoc(id); ElMessage.success('已删除'); fetchDocs()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

onMounted(() => fetchDocs())
</script>

<style scoped>
.admin-container { height: 100vh; display: flex; flex-direction: column; background: var(--bg0); }
header { height: 54px; flex: none; display: flex; align-items: center; gap: 16px; padding: 0 16px; border-bottom: 1px solid var(--line); background: linear-gradient(180deg, #0d1a2e, #0a1424); }
.brand { display: flex; align-items: center; gap: 11px; }
.brand svg { width: 30px; height: 30px; }
.brand h1 { font-size: 16px; font-weight: 700; letter-spacing: .04em; }
.brand small { display: block; font-family: var(--disp); font-size: 10px; letter-spacing: .28em; color: var(--tx3); font-weight: 600; }
.back-link { margin-left: auto; cursor: pointer; color: var(--cyan); border-color: rgba(63,208,255,.4); background: rgba(63,208,255,.08); text-decoration: none; transition: .2s; }
.back-link:hover { background: rgba(63,208,255,.18); }
.content { flex: 1; min-height: 0; display: grid; grid-template-columns: 380px 1fr; gap: 16px; padding: 16px; overflow-y: auto; }
.upload-panel, .list-panel { display: flex; flex-direction: column; }
.filter-tabs { display: inline-flex; gap: 0; margin-left: 12px; }
.filter-tabs button { background: transparent; border: 1px solid var(--line2); color: var(--tx3); font-size: 10px; padding: 2px 8px; cursor: pointer; font-family: var(--mono); transition: all .15s; }
.filter-tabs button:first-child { border-radius: 3px 0 0 3px; }
.filter-tabs button:last-child { border-radius: 0 3px 3px 0; border-left: none; }
.filter-tabs button.on { background: var(--accent); color: #0a1626; border-color: var(--accent); }
</style>
