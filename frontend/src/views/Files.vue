<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { downloadRedacted, request } from '../api'

const router = useRouter()
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const statusFilter = ref('')
let timer = null

const STATUS = {
  pending: { text: '排队中', type: 'info' },
  processing: { text: '处理中', type: 'warning' },
  completed: { text: '已完成', type: 'success' },
  needs_review: { text: '待复核', type: 'warning' },
  failed: { text: '失败', type: 'danger' },
  cancelled: { text: '已终止', type: 'info' }
}

const FILTERS = [
  { value: '', label: '全部' },
  { value: 'processing', label: '处理中' },
  { value: 'needs_review', label: '待复核' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' }
]

const hasActive = computed(() => rows.value.some((r) => ['pending', 'processing'].includes(r.status)))
const reviewCount = computed(() => rows.value.filter((r) => r.status === 'needs_review').length)

function statusOf(row) {
  return STATUS[row.status] || { text: row.status, type: 'info' }
}

async function load() {
  loading.value = true
  try {
    const query = new URLSearchParams({ page: page.value, page_size: pageSize.value })
    if (statusFilter.value) query.set('status', statusFilter.value)
    const data = await request(`/files?${query.toString()}`)
    rows.value = data.items
    total.value = data.total
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

function setFilter(value) {
  if (statusFilter.value === value) return
  statusFilter.value = value
  page.value = 1
  load()
}

async function download(row) {
  try {
    const stem = row.original_name.replace(/\.pdf$/i, '')
    await downloadRedacted(row.id, `${stem}_已脱敏.pdf`)
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function retry(row) {
  try {
    await ElMessageBox.confirm('确定要重新处理该文件吗？', '重新处理', { type: 'warning' })
    await request(`/files/${row.id}/retry`, { method: 'POST' })
    ElMessage.success('已加入队列')
    await load()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '操作失败')
  }
}

async function cancel(row) {
  try {
    await ElMessageBox.confirm('确定要终止该任务吗？', '终止任务', { type: 'warning' })
    await request(`/files/${row.id}/cancel`, { method: 'POST' })
    ElMessage.success('已请求终止')
    await load()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '操作失败')
  }
}

function open(row) {
  router.push(`/files/${row.id}`)
}

function fmt(value) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 19)
}

onMounted(async () => {
  await load()
  timer = setInterval(() => {
    if (hasActive.value) load()
  }, 3000)
})

onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="page">
    <div class="page-title">
      <div>
        <h2>我的文件</h2>
        <p class="page-subtitle">
          共 {{ total }} 个文件
          <template v-if="reviewCount">，本页 {{ reviewCount }} 个待复核</template>
        </p>
      </div>
      <el-button type="primary" @click="router.push('/upload')">上传投标文件</el-button>
    </div>

    <div class="filter-bar">
      <button
        v-for="item in FILTERS"
        :key="item.value"
        type="button"
        class="filter-chip"
        :class="{ active: statusFilter === item.value }"
        @click="setFilter(item.value)"
      >
        {{ item.label }}
      </button>
    </div>

    <div class="card file-card">
      <el-table v-loading="loading" :data="rows" stripe @row-dblclick="open">
        <el-table-column label="文件" min-width="300">
          <template #default="{ row }">
            <div class="file-cell">
              <span class="file-icon">PDF</span>
              <div class="file-cell-main">
                <div class="file-name">{{ row.original_name }}</div>
                <div class="file-meta">#{{ row.id }} · {{ row.page_count || '-' }} 页 · {{ row.doc_type || '-' }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="118">
          <template #default="{ row }">
            <el-tag :type="statusOf(row).type" effect="light">
              <span class="status-dot" style="margin-right: 5px"></span>{{ statusOf(row).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="150">
          <template #default="{ row }">
            <el-progress
              v-if="['pending', 'processing'].includes(row.status)"
              :percentage="row.progress"
              :stroke-width="8"
            />
            <span v-else class="progress-done">{{ row.status === 'needs_review' ? '处理完成' : statusOf(row).text }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="rule_version" label="规则" width="76" />
        <el-table-column label="上传时间" width="166">
          <template #default="{ row }">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="open(row)">查看</el-button>
            <el-button
              link
              type="primary"
              :disabled="!['completed', 'needs_review'].includes(row.status)"
              @click="download(row)"
            >
              下载
            </el-button>
            <el-button
              v-if="['pending', 'processing'].includes(row.status)"
              link
              type="danger"
              @click="cancel(row)"
            >
              终止
            </el-button>
            <el-button
              v-else
              link
              type="warning"
              :disabled="!['failed', 'needs_review', 'completed', 'cancelled'].includes(row.status)"
              @click="retry(row)"
            >
              重试
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          layout="total, prev, pager, next"
          :total="total"
          @current-change="load"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.filter-chip {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-500);
  border-radius: 999px;
  padding: 7px 14px;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.filter-chip:hover {
  border-color: var(--line-strong);
  color: var(--ink-900);
}

.filter-chip.active {
  border-color: var(--brand);
  background: var(--brand-soft);
  color: var(--brand);
}

.file-card {
  padding: 8px 18px 16px;
}

.file-cell {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.file-icon {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--red-soft);
  color: var(--red);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.05em;
  flex: none;
}

.file-cell-main {
  min-width: 0;
}

.file-name {
  font-weight: 600;
  color: var(--ink-900);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-meta {
  margin-top: 3px;
  color: var(--ink-400);
  font-size: 12px;
}

.progress-done {
  color: var(--ink-500);
  font-size: 12px;
  font-weight: 600;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>