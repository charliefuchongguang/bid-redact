<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { request } from '../api'
import AdminRules from './AdminRules.vue'
import AdminSystem from './AdminSystem.vue'

const router = useRouter()
const tab = ref('files')
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const statusFilter = ref('')
const stats = ref(null)

const STATUS = {
  pending: { text: '排队中', type: 'info' },
  processing: { text: '处理中', type: 'warning' },
  completed: { text: '已完成', type: 'success' },
  needs_review: { text: '待复核', type: 'warning' },
  failed: { text: '失败', type: 'danger' },
  cancelled: { text: '已终止', type: 'info' }
}

function statusOf(row) {
  return STATUS[row.status] || { text: row.status, type: 'info' }
}

function fmt(value) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 19)
}

async function loadFiles() {
  loading.value = true
  try {
    const query = new URLSearchParams({ page: page.value, page_size: pageSize.value })
    if (statusFilter.value) query.set('status', statusFilter.value)
    const data = await request(`/admin/files?${query.toString()}`)
    rows.value = data.items
    total.value = data.total
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    stats.value = await request('/admin/stats')
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function review(row, value) {
  try {
    await request(`/admin/files/${row.id}/review`, { method: 'PATCH', json: { reviewed: value } })
    ElMessage.success(value ? '已标记复核' : '已取消复核')
    await Promise.all([loadFiles(), loadStats()])
  } catch (err) {
    ElMessage.error(err.message)
  }
}

onMounted(async () => {
  await Promise.all([loadFiles(), loadStats()])
})
</script>

<template>
  <div class="page">
    <div class="page-title">
      <div>
        <h2>运营与规则</h2>
        <p class="page-subtitle">复核处理结果、维护脱敏规则，所有修改都会留下版本记录。</p>
      </div>
      <el-button v-if="tab !== 'system'" @click="loadFiles(); loadStats()">刷新</el-button>
    </div>

    <el-tabs v-model="tab">
      <el-tab-pane label="文件复核" name="files">
        <div class="card">
          <div style="margin-bottom: 14px; display: flex; gap: 12px">
            <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 160px" @change="loadFiles">
              <el-option label="排队中" value="pending" />
              <el-option label="处理中" value="processing" />
              <el-option label="已完成" value="completed" />
              <el-option label="待复核" value="needs_review" />
              <el-option label="失败" value="failed" />
              <el-option label="已终止" value="cancelled" />
            </el-select>
          </div>

          <el-table v-loading="loading" :data="rows" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="owner_id" label="上传者" width="90" />
            <el-table-column prop="original_name" label="文件名" min-width="240" show-overflow-tooltip />
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="statusOf(row).type" effect="light">{{ statusOf(row).text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="page_count" label="页数" width="80" />
            <el-table-column prop="rule_version" label="规则" width="80" />
            <el-table-column label="复核" width="120">
              <template #default="{ row }">
                <el-tag v-if="row.reviewed_at" type="success" size="small">已复核</el-tag>
                <el-tag v-else type="info" size="small">未复核</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="上传时间" width="170">
              <template #default="{ row }">{{ fmt(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="190" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="router.push(`/files/${row.id}`)">查看</el-button>
                <el-button v-if="!row.reviewed_at" link type="success" @click="review(row, true)">标记复核</el-button>
                <el-button v-else link type="warning" @click="review(row, false)">取消复核</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div style="display: flex; justify-content: flex-end; margin-top: 14px">
            <el-pagination
              v-model:current-page="page"
              v-model:page-size="pageSize"
              layout="total, prev, pager, next"
              :total="total"
              @current-change="loadFiles"
            />
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="规则库" name="rules">
        <AdminRules embedded />
      </el-tab-pane>

      <el-tab-pane label="统计" name="stats">
        <div v-if="stats">
          <div class="stat-grid">
            <div class="stat-card">
              <div class="label">文件总数</div>
              <div class="value">{{ stats.total_files }}</div>
            </div>
            <div class="stat-card">
              <div class="label">已完成</div>
              <div class="value">{{ stats.completed }}</div>
            </div>
            <div class="stat-card">
              <div class="label">待复核</div>
              <div class="value">{{ stats.needs_review }}</div>
            </div>
            <div class="stat-card">
              <div class="label">失败</div>
              <div class="value">{{ stats.failed }}</div>
            </div>
            <div class="stat-card">
              <div class="label">已终止</div>
              <div class="value">{{ stats.cancelled || 0 }}</div>
            </div>
          </div>
          <div class="stat-grid">
            <div class="stat-card">
              <div class="label">处理中</div>
              <div class="value">{{ stats.processing }}</div>
            </div>
            <div class="stat-card">
              <div class="label">排队中</div>
              <div class="value">{{ stats.pending }}</div>
            </div>
            <div class="stat-card">
              <div class="label">遮蔽框总数</div>
              <div class="value">{{ stats.boxes_total }}</div>
            </div>
            <div class="stat-card">
              <div class="label">待复核遮蔽框</div>
              <div class="value">{{ stats.boxes_pending }}</div>
            </div>
          </div>

          <div class="card">
            <h3 class="sidebar-title">按类型统计</h3>
            <div style="display: flex; gap: 10px; flex-wrap: wrap">
              <el-tag type="danger" effect="plain" size="large">个人隐私 {{ stats.by_category.personal || 0 }}</el-tag>
              <el-tag type="warning" effect="plain" size="large">商业秘密 {{ stats.by_category.secret || 0 }}</el-tag>
              <el-tag type="primary" effect="plain" size="large">企业联系 {{ stats.by_category.contact || 0 }}</el-tag>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无统计数据" />
      </el-tab-pane>

      <el-tab-pane label="系统设置" name="system">
        <AdminSystem />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>