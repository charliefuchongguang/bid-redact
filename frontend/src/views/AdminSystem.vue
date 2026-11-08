<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { request } from '../api'

const config = ref(null)
const loading = ref(false)
const saving = ref(false)
const clearing = ref(false)
const restarting = ref(false)
const tokenInput = ref('')

const warning = computed(() => config.value?.token_expiry_warning || 'unknown')
const daysLeft = computed(() => config.value?.token_days_left)
const progress = computed(() => {
  if (daysLeft.value === null || daysLeft.value === undefined) return 0
  return Math.max(0, Math.min(100, Math.round((daysLeft.value / 90) * 100)))
})
const progressStatus = computed(() => {
  if (warning.value === 'expired' || warning.value === 'urgent') return 'exception'
  if (warning.value === 'soon') return 'warning'
  return 'success'
})
const sourceText = computed(() => {
  if (config.value?.token_expiry_source === 'recorded') return '按界面录入时间计算'
  if (config.value?.token_expiry_source === 'env_mtime') return '按 .env 修改时间估算'
  return '未记录录入时间'
})
const warningText = computed(() => {
  if (warning.value === 'expired') return 'Token 已过期，扫描件将无法解析，请立即更换。'
  if (warning.value === 'urgent') return `Token 仅剩 ${daysLeft.value} 天，请尽快更换。`
  if (warning.value === 'soon') return `Token 还剩 ${daysLeft.value} 天，建议提前更换。`
  if (warning.value === 'unknown') return '无法确定 Token 录入时间，请重新保存 Token 以开始倒计时。'
  return ''
})
const warningType = computed(() => {
  if (warning.value === 'ok' || warning.value === 'unknown') return 'info'
  return warning.value === 'soon' ? 'warning' : 'error'
})

function fmtDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString('zh-CN')
}

async function load() {
  loading.value = true
  try {
    config.value = await request('/admin/system/config')
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

async function saveToken() {
  if (!tokenInput.value.trim()) {
    ElMessage.warning('请粘贴新的 MinerU Token')
    return
  }
  saving.value = true
  try {
    config.value = await request('/admin/system/mineru-token', {
      method: 'PUT',
      json: { token: tokenInput.value.trim() }
    })
    tokenInput.value = ''
    ElMessage.success('Token 已保存，新任务立即使用')
    await load()
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    saving.value = false
  }
}

async function clearToken() {
  try {
    await ElMessageBox.confirm('清除后扫描件将无法调用 MinerU，确定继续吗？', '清除 Token', {
      type: 'warning'
    })
    clearing.value = true
    config.value = await request('/admin/system/mineru-token', { method: 'DELETE' })
    ElMessage.success('Token 已清除')
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '操作失败')
  } finally {
    clearing.value = false
  }
}

async function waitForHealth() {
  for (let i = 0; i < 60; i++) {
    try {
      const response = await fetch('/api/health', { cache: 'no-store' })
      if (response.ok) {
        await load()
        ElMessage.success('服务已重启')
        return true
      }
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  ElMessage.error('重启超时，请查看服务窗口中的错误信息')
  return false
}

async function restart() {
  if (!config.value?.restart_supported) {
    ElMessage.warning('请通过「启动投标脱敏工具.bat」启动后再使用重启')
    return
  }
  const message = config.value?.active_jobs
    ? `当前有 ${config.value.active_jobs} 个任务在排队或处理中，重启会中断它们。确定继续吗？`
    : '重启会短暂中断服务，用于重新读取 Token、规则和配置。确定继续吗？'
  try {
    await ElMessageBox.confirm(message, '重启服务', { type: 'warning' })
    restarting.value = true
    try {
      await request('/admin/system/restart', { method: 'POST' })
    } catch (err) {
      if (!/无法自动重启/.test(err.message)) throw err
      ElMessage.error(err.message)
      restarting.value = false
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 1200))
    await waitForHealth()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '重启失败')
  } finally {
    restarting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="system-page">
    <div class="system-head">
      <p class="section-desc">维护 MinerU Token 和服务运行状态。当前为本地单机部署。</p>
      <el-button @click="load">刷新</el-button>
    </div>

    <div class="system-grid">
      <section class="card">
        <div class="section-head">
          <div>
            <h3 class="section-title">MinerU Token</h3>
            <p class="section-desc">用于扫描件和混合文件的 OCR 解析。Token 有效期按 3 个月估算。</p>
          </div>
          <el-tag v-if="config?.mineru_token_configured" type="success" effect="light">已配置</el-tag>
          <el-tag v-else type="info" effect="light">未配置</el-tag>
        </div>

        <div v-if="config?.mineru_token_configured" class="token-status">
          <div class="token-mask">{{ config.mineru_token_masked }}</div>
          <div class="token-meta">
            <div><span>录入时间</span><strong>{{ fmtDate(config.token_set_at) }}</strong></div>
            <div><span>预计到期</span><strong>{{ fmtDate(config.token_expires_at) }}</strong></div>
            <div><span>剩余</span><strong :class="`days-${warning}`">{{ daysLeft }} 天</strong></div>
          </div>
          <el-progress
            :percentage="progress"
            :status="progressStatus"
            :stroke-width="10"
            :show-text="false"
            style="margin-top: 14px"
          />
          <div class="token-source">{{ sourceText }}</div>
          <el-alert
            v-if="warningText"
            :type="warningType"
            :closable="false"
            show-icon
            :title="warningText"
            style="margin-top: 14px"
          />
        </div>

        <el-alert
          v-else
          type="warning"
          :closable="false"
          show-icon
          title="尚未配置 MinerU Token"
          description="文本型 PDF 可以继续处理；扫描型和混合型文件需要 Token 才能解析。"
          style="margin-bottom: 16px"
        />

        <div class="token-form">
          <el-input
            v-model="tokenInput"
            type="password"
            show-password
            placeholder="粘贴新的 MinerU Token"
            autocomplete="off"
          />
          <div class="toolbar" style="margin-top: 12px">
            <el-button type="primary" :loading="saving" @click="saveToken">保存 Token</el-button>
            <el-button v-if="config?.mineru_token_configured" :loading="clearing" @click="clearToken">清除 Token</el-button>
          </div>
          <p class="field-help">
            保存后会写入本机 .env 并立即更新当前进程。重新保存相同 Token 不会重置 3 个月倒计时。
          </p>
        </div>
      </section>

      <section class="card">
        <div class="section-head">
          <div>
            <h3 class="section-title">服务控制</h3>
            <p class="section-desc">重启会重新读取 .env、规则库和模型配置，正在处理的任务会中断。</p>
          </div>
          <el-tag :type="config?.supervised ? 'success' : 'info'" effect="light">
            {{ config?.supervised ? '启动脚本托管' : '手动运行' }}
          </el-tag>
        </div>

        <div class="service-rows">
          <div><span>运行模式</span><strong>{{ config?.supervised ? '可自动重启' : '不可自动重启' }}</strong></div>
          <div><span>排队/处理中</span><strong>{{ config?.active_jobs || 0 }} 个</strong></div>
          <div><span>配置文件</span><strong class="mono" :title="config?.env_path || ''">.env（项目根目录）</strong></div>
        </div>

        <el-alert
          v-if="!config?.supervised"
          type="info"
          :closable="false"
          show-icon
          title="当前不是由启动脚本运行"
          description="请关闭后双击「启动投标脱敏工具.bat」，重启按钮才会可用。"
          style="margin: 16px 0"
        />

        <el-button
          type="warning"
          :disabled="!config?.restart_supported"
          :loading="restarting"
          @click="restart"
        >
          {{ restarting ? '正在重启...' : '重启服务' }}
        </el-button>
        <p class="field-help">重启期间页面会短暂不可用，服务恢复后会自动提示。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.system-page {
  min-height: 300px;
}

.system-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.system-head .section-desc {
  margin: 0;
}

.system-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 0.65fr);
  gap: 18px;
  align-items: start;
}

.token-status {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
}

.token-mask {
  font-family: var(--font-mono);
  font-size: 15px;
  color: var(--ink-900);
  letter-spacing: 0.04em;
}

.token-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.token-meta div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.token-meta span {
  color: var(--ink-400);
  font-size: 11px;
}

.token-meta strong {
  font-size: 13px;
  color: var(--ink-700);
  font-variant-numeric: tabular-nums;
}

.days-ok {
  color: var(--teal);
}

.days-soon,
.days-urgent,
.days-expired {
  color: var(--red);
}

.token-source {
  margin-top: 8px;
  color: var(--ink-400);
  font-size: 11px;
}

.token-form {
  margin-top: 18px;
}

.service-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.service-rows div {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}

.service-rows div:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.service-rows span {
  color: var(--ink-400);
  font-size: 12px;
}

.service-rows strong {
  color: var(--ink-700);
  font-size: 12px;
  text-align: right;
  word-break: break-all;
  line-height: 1.6;
}

@media (max-width: 980px) {
  .system-grid {
    grid-template-columns: 1fr;
  }

  .token-meta {
    grid-template-columns: 1fr;
  }
}
</style>