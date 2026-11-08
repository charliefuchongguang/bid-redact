<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { uploadFile } from '../api'

const router = useRouter()
const fileInput = ref(null)
const selected = ref(null)
const dragging = ref(false)
const uploading = ref(false)
const progress = ref(0)
const MAX_BYTES = 200 * 1024 * 1024

function pick() {
  if (!uploading.value) fileInput.value?.click()
}

function setFile(file) {
  if (!file) return
  if (!/\.pdf$/i.test(file.name)) {
    ElMessage.warning('仅支持 PDF 文件')
    return
  }
  if (file.size > MAX_BYTES) {
    ElMessage.warning('文件不能超过 200MB')
    return
  }
  selected.value = file
  progress.value = 0
}

function onFileChange(event) {
  setFile(event.target.files?.[0])
  event.target.value = ''
}

function onDrop(event) {
  dragging.value = false
  setFile(event.dataTransfer?.files?.[0])
}

async function submit() {
  if (!selected.value || uploading.value) return
  uploading.value = true
  progress.value = 0
  try {
    const data = await uploadFile(selected.value, (value) => {
      progress.value = value
    })
    ElMessage.success('上传成功，已加入处理队列')
    router.push(`/files/${data.id}`)
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    uploading.value = false
  }
}

function humanSize(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}
</script>

<template>
  <div class="page upload-page">
    <div class="page-title">
      <div>
        <h2>上传投标文件</h2>
        <p class="page-subtitle">上传后系统会自动识别并遮蔽身份证号、手机号、证书编号、报价等敏感信息。</p>
      </div>
      <el-button @click="router.push('/files')">返回列表</el-button>
    </div>

    <div class="upload-grid">
      <section class="upload-panel">
        <div
          class="drop-zone"
          :class="{ active: dragging }"
          @click="pick"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="onDrop"
        >
          <div class="drop-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
              <path d="M14 3v5h5M12 18v-6M9.5 14.5 12 12l2.5 2.5" />
            </svg>
          </div>
          <div class="drop-title">点击选择文件，或拖拽 PDF 到此处</div>
          <div class="drop-hint">仅支持 PDF，单文件不超过 200MB；加密文件无法处理</div>
          <input ref="fileInput" type="file" accept=".pdf,application/pdf" hidden @change="onFileChange" />
        </div>

        <div v-if="selected" class="selected-file">
          <div class="selected-file-main">
            <span class="file-badge">PDF</span>
            <div>
              <div class="selected-name">{{ selected.name }}</div>
              <div class="muted">{{ humanSize(selected.size) }}</div>
            </div>
          </div>
          <el-progress
            v-if="uploading"
            :percentage="progress"
            :stroke-width="10"
            :show-text="false"
            style="margin-top: 16px"
          />
          <div class="toolbar" style="margin-top: 18px">
            <el-button type="primary" :loading="uploading" @click="submit">开始脱敏</el-button>
            <el-button :disabled="uploading" @click="selected = null">重新选择</el-button>
          </div>
        </div>

        <div class="upload-faq">
          <div><strong>加密 PDF</strong><span>需要先解除密码再上传。</span></div>
          <div><strong>扫描件</strong><span>会自动调用 MinerU 解析，页数多时耗时更长。</span></div>
          <div><strong>待复核</strong><span>低置信度框可在结果页逐项确认。</span></div>
        </div>
      </section>

      <aside class="upload-aside">
        <div class="card">
          <h3 class="sidebar-title">处理流程</h3>
          <ol class="flow-list">
            <li><span>1</span><div><strong>上传 PDF</strong><p>支持文本型、扫描型和混合型文件。</p></div></li>
            <li><span>2</span><div><strong>自动识别</strong><p>规则库 + 人脸 + 表格检测协同定位敏感信息。</p></div></li>
            <li><span>3</span><div><strong>复核下载</strong><p>待复核项会在结果页标出，确认后下载脱敏件。</p></div></li>
          </ol>
        </div>
        <div class="notice-card">
          <strong>安全说明</strong>
          <p>系统先物理移除内容，再绘制中性灰马赛克。原件与脱敏件均只对登录用户开放。</p>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.upload-page {
  max-width: 1080px;
}

.upload-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 20px;
  align-items: start;
}

.upload-panel {
  min-width: 0;
}

.selected-file {
  margin-top: 22px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
}

.selected-file-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-badge {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--red-soft);
  color: var(--red);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.06em;
}

.selected-name {
  font-weight: 650;
  margin-bottom: 3px;
  word-break: break-all;
}

.upload-faq {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 18px;
}

.upload-faq > div {
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.upload-faq strong {
  display: block;
  color: var(--ink-700);
  font-size: 13px;
  margin-bottom: 4px;
}

.upload-faq span {
  color: var(--ink-500);
  font-size: 13px;
  line-height: 1.6;
}

.upload-aside {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.flow-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.flow-list li {
  display: flex;
  gap: 12px;
}

.flow-list li > span {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 12px;
  font-weight: 700;
  flex: none;
}

.flow-list strong {
  font-size: 13px;
}

.flow-list p {
  margin: 4px 0 0;
  color: var(--ink-500);
  font-size: 12px;
  line-height: 1.6;
}

.notice-card {
  padding: 16px 18px;
  border-radius: var(--radius);
  border: 1px solid #c8d8ec;
  background: var(--brand-soft);
}

.notice-card strong {
  font-size: 13px;
  color: var(--brand-strong);
}

.notice-card p {
  margin: 6px 0 0;
  color: #35506f;
  font-size: 13px;
  line-height: 1.7;
}

@media (max-width: 900px) {
  .upload-grid {
    grid-template-columns: 1fr;
  }

  .upload-faq {
    grid-template-columns: 1fr;
  }
}
</style>