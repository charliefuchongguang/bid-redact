<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { downloadRedacted, getUser, request, requestBlob } from '../api'

const props = defineProps({ id: { type: String, required: true } })
const fileId = Number(props.id)
const router = useRouter()

const fileInfo = ref(null)
const status = ref(null)
const boxes = ref([])
const meta = ref(null)
const currentPage = ref(1)
const pageUrl = ref('')
const pageLoading = ref(false)
const dpi = ref(150)
const showLabels = ref(true)
const refreshing = ref(false)
const loadedOnce = ref(false)
const boxLoading = ref(false)
const pendingOnly = ref(false)
const previewVersion = ref(Date.now())
const editMode = ref(false)
const adjustMode = ref(false)
const selectedBoxId = ref(null)
const boxEdit = ref(null)
const boxSaving = ref(false)
const draft = ref(null)
const dragStart = ref(null)
const boxDialog = ref(false)
const newBox = ref({ page: 1, x0: 0, y0: 0, x1: 0, y1: 0, category: 'personal', mode: 'rect' })
let timer = null

const isAdmin = computed(() => getUser()?.role === 'admin')

const STATUS = {
  pending: { text: '排队中', type: 'info' },
  processing: { text: '处理中', type: 'warning' },
  completed: { text: '已完成', type: 'success' },
  needs_review: { text: '待复核', type: 'warning' },
  failed: { text: '失败', type: 'danger' },
  cancelled: { text: '已终止', type: 'info' }
}

const CATEGORY = {
  personal: '个人隐私',
  secret: '商业秘密',
  contact: '企业联系'
}

const RULE_LABEL = {
  'RED-01': '身份证号',
  'RED-02': '身份证照片',
  'RED-03': '手机号',
  'RED-04': '固定电话',
  'RED-05': '个人邮箱',
  'RED-06': '家庭住址',
  'RED-07': '银行卡号',
  'RED-08': '证书编号',
  'RED-09': '银行账号',
  'RED-10': '投标函总报价',
  'RED-11': '报价明细/合价',
  'RED-12': '成本构成/财务数据',
  'RED-13': '合同金额',
  'RED-14': '联系人手机',
  'RED-15': '私人微信',
  'RED-16': '基本存款账户编号',
  'RED-17': '投标/履约保证金',
  'RED-18': '银行回执/验证码',
  'RED-19': '年度营业额/合同价格',
  'RED-20': '合同保密条款',
  'RED-21': '大写金额',
  'RED-22': '开户行名称',
  'RED-23': '小写金额',
  'RED-24': '银行账号/长数字账号',
  'RED-25': '人员证书/验证码',
  'RED-26': '表格证书编号',
  'RED-27': '表格联系电话',
  'RED-28': '证件号码',
  'RED-29': '表格证号列',
  'FACE-01': '人脸',
  'BLUE-STAMP': '蓝色印章',
  'SS-CODE': '社保条码/验证码'
}

function ruleLabel(id) {
  return RULE_LABEL[id] || id
}

const ready = computed(() => ['completed', 'needs_review'].includes(status.value?.status))
const statusMeta = computed(() => STATUS[status.value?.status] || { text: status.value?.status || '-', type: 'info' })
const currentMeta = computed(() => meta.value?.pages?.[currentPage.value - 1] || null)
const pageBoxes = computed(() =>
  boxes.value
    .filter((box) => box.page === currentPage.value)
    .sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0)
)
const selectedBox = computed(
  () => boxes.value.find((box) => box.id === selectedBoxId.value) || null
)
const loadingText = computed(() =>
  boxSaving.value ? '正在从原文件重建脱敏件...' : '加载页面预览...'
)
const categoryCounts = computed(() => {
  const counts = { personal: 0, secret: 0, contact: 0 }
  for (const box of boxes.value) counts[box.category] = (counts[box.category] || 0) + 1
  return counts
})
const pendingCount = computed(() => boxes.value.filter((box) => box.state !== 'redacted').length)
const reviewed = computed(() => Boolean(fileInfo.value?.reviewed_at))
const sidebarBoxes = computed(() =>
  pendingOnly.value ? boxes.value.filter((box) => box.state !== 'redacted') : boxes.value
)

function fmt(value) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 19)
}

async function loadFile() {
  fileInfo.value = await request(`/files/${fileId}`)
}

async function loadStatus() {
  status.value = await request(`/files/${fileId}/status`)
}

async function toggleReview() {
  try {
    await request(`/admin/files/${fileId}/review`, {
      method: 'PATCH',
      json: { reviewed: !reviewed.value }
    })
    ElMessage.success(reviewed.value ? '已取消复核' : '已标记复核')
    await loadFile()
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function loadBoxesMeta() {
  const [boxData, metaData] = await Promise.all([
    request(`/files/${fileId}/boxes`),
    request(`/files/${fileId}/page-meta`)
  ])
boxes.value = boxData
  meta.value = metaData
  if (selectedBoxId.value && !boxData.some((box) => box.id === selectedBoxId.value)) {
    selectedBoxId.value = null
  }
  if (currentPage.value > (metaData.page_count || 1)) currentPage.value = 1
}

async function loadPage() {
  if (!ready.value) return
  pageLoading.value = true
  try {
    const blob = await requestBlob(
      `/files/${fileId}/preview/${currentPage.value}?dpi=${dpi.value}&v=${previewVersion.value}`
    )
    if (pageUrl.value) URL.revokeObjectURL(pageUrl.value)
    pageUrl.value = URL.createObjectURL(blob)
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    pageLoading.value = false
  }
}

async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.all([loadFile(), loadStatus()])
    if (ready.value && !loadedOnce.value) {
      await loadBoxesMeta()
      await loadPage()
      loadedOnce.value = true
    }
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    refreshing.value = false
  }
}

async function download() {
  try {
    const stem = (fileInfo.value?.original_name || `文件${fileId}`).replace(/\.pdf$/i, '')
    await downloadRedacted(fileId, `${stem}_已脱敏.pdf`)
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function retry() {
  try {
    await ElMessageBox.confirm('确定要重新处理该文件吗？', '重新处理', { type: 'warning' })
    await request(`/files/${fileId}/retry`, { method: 'POST' })
    loadedOnce.value = false
    boxes.value = []
    meta.value = null
    if (pageUrl.value) URL.revokeObjectURL(pageUrl.value)
    pageUrl.value = ''
    ElMessage.success('已重新加入队列')
    await refresh()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '操作失败')
  }
}

function boxStyle(box) {
  const page = currentMeta.value
  if (!page) return {}
  return {
    left: `${(box.x0 / page.width) * 100}%`,
    top: `${(box.y0 / page.height) * 100}%`,
    width: `${((box.x1 - box.x0) / page.width) * 100}%`,
    height: `${((box.y1 - box.y0) / page.height) * 100}%`
  }
}

function boxClass(box) {
  return `${box.category}${box.state !== 'redacted' ? ' pending' : ''}`
}

function jumpTo(box) {
  currentPage.value = box.page
}

function toggleAdjustMode(value) {
  if (value) {
    editMode.value = false
    draft.value = null
  } else {
    selectedBoxId.value = null
  }
}

function toggleEditMode(value) {
  if (value) {
    adjustMode.value = false
    selectedBoxId.value = null
  }
}

function selectBox(box) {
  if (!adjustMode.value || boxSaving.value) return
  selectedBoxId.value = box.id
}

function clearSelection() {
  if (!boxSaving.value) selectedBoxId.value = null
}

function roundCoord(value) {
  return Math.round(value * 10) / 10
}

function onBoxMouseDown(box, event, mode) {
  if (!adjustMode.value || boxSaving.value || !currentMeta.value) return
  event.preventDefault()
  event.stopPropagation()
  selectedBoxId.value = box.id
  const pageElement = event.currentTarget.closest('.pdf-page')
  if (!pageElement) return
  stopBoxEdit()
  boxEdit.value = {
    box,
    mode,
    startX: event.clientX,
    startY: event.clientY,
    pageRect: pageElement.getBoundingClientRect(),
    pageWidth: currentMeta.value.width,
    pageHeight: currentMeta.value.height,
    original: { x0: box.x0, y0: box.y0, x1: box.x1, y1: box.y1 }
  }
  document.addEventListener('mousemove', onBoxMouseMove)
  document.addEventListener('mouseup', onBoxMouseUp)
}

function onBoxMouseMove(event) {
  const edit = boxEdit.value
  if (!edit || !edit.pageRect.width || !edit.pageRect.height) return
  event.preventDefault()
  const dx = ((event.clientX - edit.startX) / edit.pageRect.width) * edit.pageWidth
  const dy = ((event.clientY - edit.startY) / edit.pageRect.height) * edit.pageHeight
  const minSize = 3
  const pageWidth = edit.pageWidth
  const pageHeight = edit.pageHeight
  const box = edit.box
  const original = edit.original

  if (edit.mode === 'move') {
    let x0 = original.x0 + dx
    let x1 = original.x1 + dx
    let y0 = original.y0 + dy
    let y1 = original.y1 + dy
    if (x0 < 0) {
      x1 -= x0
      x0 = 0
    }
    if (x1 > pageWidth) {
      x0 -= x1 - pageWidth
      x1 = pageWidth
    }
    if (y0 < 0) {
      y1 -= y0
      y0 = 0
    }
    if (y1 > pageHeight) {
      y0 -= y1 - pageHeight
      y1 = pageHeight
    }
    box.x0 = roundCoord(x0)
    box.x1 = roundCoord(x1)
    box.y0 = roundCoord(y0)
    box.y1 = roundCoord(y1)
    return
  }

  let x0 = original.x0
  let y0 = original.y0
  let x1 = original.x1
  let y1 = original.y1
  if (edit.mode.includes('w')) x0 = Math.min(Math.max(original.x0 + dx, 0), x1 - minSize)
  if (edit.mode.includes('e')) x1 = Math.max(Math.min(original.x1 + dx, pageWidth), x0 + minSize)
  if (edit.mode.includes('n')) y0 = Math.min(Math.max(original.y0 + dy, 0), y1 - minSize)
  if (edit.mode.includes('s')) y1 = Math.max(Math.min(original.y1 + dy, pageHeight), y0 + minSize)
  box.x0 = roundCoord(x0)
  box.x1 = roundCoord(x1)
  box.y0 = roundCoord(y0)
  box.y1 = roundCoord(y1)
}

function stopBoxEdit() {
  document.removeEventListener('mousemove', onBoxMouseMove)
  document.removeEventListener('mouseup', onBoxMouseUp)
  boxEdit.value = null
}

async function onBoxMouseUp() {
  const edit = boxEdit.value
  document.removeEventListener('mousemove', onBoxMouseMove)
  document.removeEventListener('mouseup', onBoxMouseUp)
  boxEdit.value = null
  if (!edit) return
  const box = edit.box
  const original = edit.original
  if (
    Math.abs(box.x0 - original.x0) < 0.2 &&
    Math.abs(box.y0 - original.y0) < 0.2 &&
    Math.abs(box.x1 - original.x1) < 0.2 &&
    Math.abs(box.y1 - original.y1) < 0.2
  ) {
    return
  }
  await saveBoxPosition(box, original)
}

async function saveBoxPosition(box, original) {
  boxSaving.value = true
  boxLoading.value = true
  try {
    await request(`/admin/boxes/${box.id}`, {
      method: 'PATCH',
      json: {
        page: box.page,
        x0: box.x0,
        y0: box.y0,
        x1: box.x1,
        y1: box.y1
      }
    })
    ElMessage.success('遮蔽框位置已更新')
    const keepId = box.id
    resetLoaded()
    await refresh()
    selectedBoxId.value = keepId
  } catch (err) {
    Object.assign(box, original)
    ElMessage.error(err.message)
  } finally {
    boxSaving.value = false
    boxLoading.value = false
  }
}

async function ignoreSelectedBox() {
  const box = selectedBox.value
  if (!box) return
  if (boxes.value.length <= 1) {
    ElMessage.warning('这是最后一个遮蔽框，不能忽略')
    return
  }
  try {
    await ElMessageBox.confirm(
      '忽略后会从原文件重建脱敏件，该区域会恢复显示。确定忽略这个遮蔽框吗？',
      '忽略此框',
      { type: 'warning' }
    )
    boxLoading.value = true
    await request(`/admin/boxes/${box.id}`, { method: 'DELETE' })
    selectedBoxId.value = null
    ElMessage.success('已忽略此遮蔽框')
    resetLoaded()
    await refresh()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '操作失败')
  } finally {
    boxLoading.value = false
  }
}

function resetLoaded() {
  loadedOnce.value = false
  boxes.value = []
  selectedBoxId.value = null
  previewVersion.value = Date.now()
}

async function cancelTask() {
  try {
    await ElMessageBox.confirm('确定要终止该任务吗？', '终止任务', { type: 'warning' })
    await request(`/files/${fileId}/cancel`, { method: 'POST' })
    ElMessage.success('已请求终止')
    await refresh()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '操作失败')
  }
}

function onPageMouseDown(event) {
  if (adjustMode.value) {
    selectedBoxId.value = null
    return
  }
  if (!editMode.value || !currentMeta.value) return
  const rect = event.currentTarget.getBoundingClientRect()
  const x = ((event.clientX - rect.left) / rect.width) * currentMeta.value.width
  const y = ((event.clientY - rect.top) / rect.height) * currentMeta.value.height
  dragStart.value = { x, y }
  draft.value = { x0: x, y0: y, x1: x, y1: y }
}

function onPageMouseMove(event) {
  if (!dragStart.value || !currentMeta.value) return
  const rect = event.currentTarget.getBoundingClientRect()
  const x = Math.min(
    Math.max(((event.clientX - rect.left) / rect.width) * currentMeta.value.width, 0),
    currentMeta.value.width
  )
  const y = Math.min(
    Math.max(((event.clientY - rect.top) / rect.height) * currentMeta.value.height, 0),
    currentMeta.value.height
  )
  draft.value = {
    x0: Math.min(dragStart.value.x, x),
    y0: Math.min(dragStart.value.y, y),
    x1: Math.max(dragStart.value.x, x),
    y1: Math.max(dragStart.value.y, y)
  }
}

function cancelDrag() {
  dragStart.value = null
  draft.value = null
}

function onPageMouseUp() {
  if (!dragStart.value || !draft.value) return
  const box = draft.value
  dragStart.value = null
  if (box.x1 - box.x0 < 3 || box.y1 - box.y0 < 3) {
    draft.value = null
    return
  }
  newBox.value = {
    page: currentPage.value,
    x0: Math.round(box.x0 * 10) / 10,
    y0: Math.round(box.y0 * 10) / 10,
    x1: Math.round(box.x1 * 10) / 10,
    y1: Math.round(box.y1 * 10) / 10,
    category: 'personal',
    mode: 'rect'
  }
  boxDialog.value = true
}

const draftStyle = computed(() => {
  const page = currentMeta.value
  if (!page || !draft.value) return {}
  const box = draft.value
  return {
    left: `${(box.x0 / page.width) * 100}%`,
    top: `${(box.y0 / page.height) * 100}%`,
    width: `${((box.x1 - box.x0) / page.width) * 100}%`,
    height: `${((box.y1 - box.y0) / page.height) * 100}%`
  }
})

async function confirmAddBox() {
  boxLoading.value = true
  try {
    await request(`/admin/files/${fileId}/boxes`, { method: 'POST', json: newBox.value })
    boxDialog.value = false
    draft.value = null
    ElMessage.success('已新增遮蔽框')
    resetLoaded()
    await refresh()
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    boxLoading.value = false
  }
}

async function removeBox(row) {
  try {
    await ElMessageBox.confirm('确定删除该遮蔽框吗？删除后会重新生成脱敏件', '删除遮蔽框', {
      type: 'warning'
    })
    boxLoading.value = true
    await request(`/admin/boxes/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除遮蔽框')
    resetLoaded()
    await refresh()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '操作失败')
  } finally {
    boxLoading.value = false
  }
}

watch([currentPage, dpi], () => {
  stopBoxEdit()
  if (selectedBox.value && selectedBox.value.page !== currentPage.value) {
    selectedBoxId.value = null
  }
  if (ready.value) loadPage()
})

onMounted(async () => {
  await refresh()
  timer = setInterval(() => {
    if (!ready.value) refresh()
  }, 2000)
})

onUnmounted(() => {
  clearInterval(timer)
  stopBoxEdit()
  if (pageUrl.value) URL.revokeObjectURL(pageUrl.value)
})
</script>

<template>
  <div class="page">
    <div class="page-title result-title">
      <div class="result-heading">
        <div class="meta-row">
<el-button @click="router.push('/files')">返回</el-button>
          <el-tag :type="statusMeta.type" effect="light">{{ statusMeta.text }}</el-tag>
        </div>
        <h2 class="result-file-name">{{ fileInfo?.original_name || '处理结果' }}</h2>
      </div>
<div class="toolbar">
        <el-button v-if="isAdmin" :type="reviewed ? 'success' : 'default'" plain @click="toggleReview">
          {{ reviewed ? '取消复核' : '标记已复核' }}
        </el-button>
        <el-button :disabled="!ready" @click="download">下载脱敏件</el-button>
        <el-button
          v-if="status && ['pending', 'processing'].includes(status.status)"
          type="danger"
          plain
          @click="cancelTask"
        >
          终止
        </el-button>
        <el-button
          type="warning"
          plain
          :disabled="!status || ['pending', 'processing'].includes(status.status)"
          @click="retry"
        >
          重新处理
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="status?.status === 'failed'"
      type="error"
      :closable="false"
      show-icon
      title="处理失败"
      :description="status.fail_reason || '未知错误'"
      style="margin-bottom: 16px"
    />
    <el-alert
      v-else-if="status && !ready"
      type="info"
      :closable="false"
      show-icon
      :title="status.status === 'processing' ? '正在处理' : `排队中${status.queue_position ? `，前方 ${status.queue_position} 个任务` : ''}`"
      style="margin-bottom: 16px"
    >
      <el-progress :percentage="status.progress" :stroke-width="12" style="max-width: 460px" />
    </el-alert>
    <el-alert
      v-else-if="status?.status === 'cancelled'"
      type="info"
      :closable="false"
      show-icon
      title="任务已终止"
      description="本地已停止处理；如云端解析仍在进行，其结果将被忽略。可点击「重新处理」重新开始。"
      style="margin-bottom: 16px"
    />
    <el-alert
      v-else-if="status?.status === 'needs_review'"
      type="warning"
      :closable="false"
      show-icon
title="存在待人工复核的遮蔽框"
      description="低置信度或扫描表格近似定位的遮蔽框已标记为待复核。确认无误后可点右上方「标记已复核」；需要逐项检查时，在右侧遮蔽明细中定位。"
      style="margin-bottom: 16px"
    />

    <div class="page-shell">
      <div>
        <div class="card" style="padding: 12px 16px; margin-bottom: 12px; display: flex; align-items: center; gap: 16px">
<el-button :disabled="currentPage <= 1" @click="currentPage--">上一页</el-button>
          <span class="muted" style="font-size: 13px">第</span>
          <el-input-number
            v-model="currentPage"
            :min="1"
            :max="meta?.page_count || fileInfo?.page_count || 1"
            size="small"
            controls-position="right"
            style="width: 108px"
          />
          <span class="muted" style="font-size: 13px">/ {{ meta?.page_count || fileInfo?.page_count || 0 }} 页</span>
          <el-button :disabled="!meta || currentPage >= meta.page_count" @click="currentPage++">下一页</el-button>
          <div style="flex: 1"></div>
<el-switch v-model="showLabels" active-text="显示标签" />
          <el-switch v-if="isAdmin" v-model="editMode" active-text="框选新增" :disabled="boxSaving" @change="toggleEditMode" />
          <el-switch v-if="isAdmin" v-model="adjustMode" active-text="调整框" :disabled="boxSaving" @change="toggleAdjustMode" />
          <el-select v-model="dpi" style="width: 110px">
            <el-option :value="110" label="标准" />
            <el-option :value="150" label="清晰" />
            <el-option :value="200" label="高清" />
          </el-select>
        </div>

        <Teleport to="body">
          <div v-if="isAdmin && adjustMode" class="box-edit-bar">
            <template v-if="selectedBox">
              <span>
                已选中：第 {{ selectedBox.page }} 页 · {{ ruleLabel(selectedBox.rule_id) }}
              </span>
              <div class="toolbar">
                <el-button size="small" type="danger" plain :disabled="boxes.length <= 1" @click="ignoreSelectedBox">
                  忽略此框
                </el-button>
                <el-button size="small" text @click="clearSelection">取消选中</el-button>
              </div>
            </template>
            <span v-else class="muted">点击一个遮蔽框后，可拖动位置或拖四角缩放。</span>
          </div>
        </Teleport>

        <div v-loading="pageLoading || boxLoading" :element-loading-text="loadingText" class="pdf-stage">
          <div
            v-if="pageUrl"
            class="pdf-page"
            style="width: min(100%, 880px)"
            :style="{ cursor: editMode ? 'crosshair' : 'default' }"
            @mousedown="onPageMouseDown"
            @mousemove="onPageMouseMove"
            @mouseup="onPageMouseUp"
            @mouseleave="cancelDrag"
          >
            <img :src="pageUrl" alt="PDF 页面预览" />
<div
              v-for="box in pageBoxes"
              :key="box.id"
              class="hit-box"
              :class="[boxClass(box), { selectable: isAdmin && adjustMode, selected: selectedBoxId === box.id }]"
              :style="boxStyle(box)"
              @mousedown.stop="onBoxMouseDown(box, $event, 'move')"
            >
              <span v-if="showLabels" class="hit-label">
                {{ CATEGORY[box.category] || box.category }} · {{ ruleLabel(box.rule_id) }}
              </span>
              <template v-if="isAdmin && adjustMode && selectedBoxId === box.id">
                <span class="resize-handle nw" @mousedown.stop="onBoxMouseDown(box, $event, 'nw')"></span>
                <span class="resize-handle ne" @mousedown.stop="onBoxMouseDown(box, $event, 'ne')"></span>
                <span class="resize-handle sw" @mousedown.stop="onBoxMouseDown(box, $event, 'sw')"></span>
                <span class="resize-handle se" @mousedown.stop="onBoxMouseDown(box, $event, 'se')"></span>
              </template>
            </div>
            <div v-if="draft" class="draft-box" :style="draftStyle"></div>
          </div>
          <el-empty v-else description="处理完成后显示页面预览" />
        </div>
      </div>

      <aside class="result-sidebar">
        <div class="card">
          <h3 class="sidebar-title">处理概览</h3>
          <div class="overview-metrics">
            <div class="metric">
              <span>遮蔽总数</span>
              <strong>{{ boxes.length }}</strong>
            </div>
            <div class="metric warning">
              <span>待复核</span>
              <strong>{{ pendingCount }}</strong>
            </div>
          </div>
          <div class="category-pills">
            <span class="category-pill personal">个人隐私 {{ categoryCounts.personal }}</span>
            <span class="category-pill secret">商业秘密 {{ categoryCounts.secret }}</span>
            <span class="category-pill contact">企业联系 {{ categoryCounts.contact }}</span>
          </div>
        </div>

        <div class="card">
          <h3 class="sidebar-title">文件信息</h3>
          <dl class="info-list">
            <div><dt>页数</dt><dd>{{ fileInfo?.page_count || '-' }}</dd></div>
            <div><dt>文档类型</dt><dd>{{ fileInfo?.doc_type || '-' }}</dd></div>
            <div><dt>规则版本</dt><dd>v{{ fileInfo?.rule_version || '-' }}</dd></div>
            <div><dt>上传时间</dt><dd>{{ fmt(fileInfo?.created_at) }}</dd></div>
            <div>
              <dt>复核状态</dt>
              <dd>
                <el-tag v-if="fileInfo?.reviewed_at" type="success" size="small">已复核</el-tag>
                <el-tag v-else type="info" size="small">未复核</el-tag>
              </dd>
            </div>
          </dl>
        </div>

        <div class="card">
<div class="section-head" style="margin-bottom: 10px">
            <h3 class="sidebar-title" style="margin: 0">遮蔽明细</h3>
            <el-switch v-model="pendingOnly" size="small" active-text="只看待复核" />
          </div>
          <div class="box-count">{{ sidebarBoxes.length }} 项</div>
          <div v-if="sidebarBoxes.length" class="box-list">
            <button
              v-for="box in sidebarBoxes"
              :key="box.id"
              type="button"
              class="box-list-item"
              @click="jumpTo(box)"
            >
              <span class="page-chip">P{{ box.page }}</span>
              <span class="box-main">
                <span class="box-rule">{{ ruleLabel(box.rule_id) }}</span>
                <span class="box-category">{{ CATEGORY[box.category] || box.category }}</span>
              </span>
              <el-tag :type="box.state === 'redacted' ? 'success' : 'warning'" size="small" effect="plain">
                {{ box.state === 'redacted' ? '已遮蔽' : '待复核' }}
              </el-tag>
            </button>
          </div>
          <el-empty v-else :description="pendingOnly ? '没有待复核项' : '暂无遮蔽项'" :image-size="64" />
        </div>
      </aside>
    </div>

    <el-dialog v-model="boxDialog" title="新增遮蔽框" width="380px">
      <el-form label-width="72px">
        <el-form-item label="页码">{{ newBox.page }}</el-form-item>
        <el-form-item label="类型">
          <el-select v-model="newBox.category" style="width: 100%">
            <el-option label="个人隐私" value="personal" />
            <el-option label="商业秘密" value="secret" />
            <el-option label="企业联系" value="contact" />
          </el-select>
        </el-form-item>
        <el-form-item label="坐标">
          <span class="mono">
            ({{ newBox.x0 }}, {{ newBox.y0 }}) - ({{ newBox.x1 }}, {{ newBox.y1 }})
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="boxDialog = false; draft = null">取消</el-button>
        <el-button type="primary" @click="confirmAddBox">新增并重新生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<style scoped>
.box-edit-bar {
  position: fixed;
  top: 76px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  width: min(calc(100vw - 64px), 1216px);
  margin: 0;
  padding: 10px 14px;
  border: 1px solid #c8d8ec;
  border-radius: var(--radius-sm);
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 13px;
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}

.hit-box.selectable {
  pointer-events: auto;
  cursor: move;
}

.hit-box.selected {
  outline: 2px solid var(--brand);
  outline-offset: 1px;
  box-shadow: 0 0 0 3px rgba(29, 79, 145, 0.18);
}

.resize-handle {
  position: absolute;
  width: 10px;
  height: 10px;
  border: 2px solid var(--brand);
  border-radius: 2px;
  background: #fff;
  z-index: 2;
}

.resize-handle.nw {
  left: -6px;
  top: -6px;
  cursor: nwse-resize;
}

.resize-handle.ne {
  right: -6px;
  top: -6px;
  cursor: nesw-resize;
}

.resize-handle.sw {
  left: -6px;
  bottom: -6px;
  cursor: nesw-resize;
}

.resize-handle.se {
  right: -6px;
  bottom: -6px;
  cursor: nwse-resize;
}

.result-title {
  align-items: flex-start;
}

.result-heading {
  min-width: 0;
}

.result-file-name {
  margin: 10px 0 0;
  font-size: 22px;
  line-height: 1.35;
  word-break: break-all;
}

.result-sidebar {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.overview-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.overview-metrics {
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.metric {
  padding: 12px 0;
  border-radius: 0;
  background: transparent;
  border: 0;
}

.metric + .metric {
  padding-left: 16px;
  border-left: 1px solid var(--line);
}

.metric span {
  display: block;
  color: var(--ink-500);
  font-size: 12px;
}

.metric strong {
  display: block;
  margin-top: 4px;
  font-size: 24px;
  line-height: 1;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}

.metric.warning strong {
  color: var(--amber);
}

.category-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.category-pill {
  padding: 4px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid transparent;
}

.category-pill.personal {
  color: #8f1d14;
  background: var(--red-soft);
  border-color: #f0c1bc;
}

.category-pill.secret {
  color: #7c3f06;
  background: var(--amber-soft);
  border-color: #f0d3a7;
}

.category-pill.contact {
  color: #19467f;
  background: var(--brand-soft);
  border-color: #c8d8ec;
}

.info-list {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.info-list > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}

.info-list > div:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.info-list dt {
  color: var(--ink-500);
  font-size: 12px;
}

.info-list dd {
  margin: 0;
  color: var(--ink-700);
  font-size: 12px;
  font-weight: 600;
  text-align: right;
  word-break: break-all;
}

.box-count {
  margin: -4px 0 8px;
  color: var(--ink-400);
  font-size: 12px;
}

.box-list {
  max-height: 340px;
  overflow: auto;
  display: flex;
  flex-direction: column;
}

.box-list-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 2px;
  border: 0;
  border-top: 1px solid var(--line);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.box-list-item:first-child {
  border-top: 0;
}

.box-list-item:hover {
  background: var(--surface-muted);
}

.page-chip {
  min-width: 34px;
  padding: 3px 6px;
  border-radius: 5px;
  background: var(--canvas-deep);
  color: var(--ink-500);
  font-size: 10px;
  font-weight: 700;
  text-align: center;
  font-variant-numeric: tabular-nums;
  flex: none;
}

.box-main {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.box-rule {
  color: var(--ink-900);
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.box-category {
  color: var(--ink-400);
  font-size: 11px;
}

@media (max-width: 720px) {
  .box-edit-bar {
    top: 128px;
    width: calc(100vw - 36px);
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
