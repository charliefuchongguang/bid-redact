<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Delete, EditPen, MoreFilled, Plus, Search } from '@element-plus/icons-vue'
import { exportRulesYaml, request } from '../api'
import TagEditor from '../components/TagEditor.vue'

const props = defineProps({ embedded: { type: Boolean, default: false } })

const CATEGORIES = [
  { key: 'personal', label: '个人隐私', tone: 'danger' },
  { key: 'secret', label: '商业秘密', tone: 'warning' },
  { key: 'contact', label: '企业联系', tone: 'primary' }
]
const MATCH_TYPES = [
  { value: 'semantic', label: '关键词' },
  { value: 'regex', label: '正则表达式' },
  { value: 'table', label: '表格' },
  { value: 'image', label: '图片' }
]
const REDACT_MODES = [
  { value: 'rect', label: '局部矩形', scope: '局部' },
  { value: 'cell', label: '表格单元格', scope: '单元格' },
  { value: 'card', label: '整张卡片', scope: '整卡' },
  { value: 'image', label: '整张图片', scope: '整图' }
]
const STATUS = {
  draft: { text: '草稿', type: 'warning' },
  active: { text: '生效中', type: 'success' },
  archived: { text: '已归档', type: 'info' }
}

const versions = ref([])
const selectedId = ref(null)
const detail = ref(null)
const loading = ref(false)
const actionLoading = ref(false)
const search = ref('')
const categoryFilter = ref('all')
const typeFilter = ref('all')
const payload = ref(null)
const rules = ref([])
const drawer = ref(false)
const editingId = ref(null)
const bottomPanels = ref([])
const advancedPanels = ref([])
const previewText = ref('证书编号：AD244400388，联系人：李四 13800138000')
const validationErrors = ref([])
const jsonText = ref('')
const yamlText = ref('')
const rawTab = ref('json')
const lastRawTab = ref('json')
const rawLoading = ref(false)
const importDialog = ref(false)
const importText = ref('')
const importVersion = ref('')

const form = reactive(blankForm())

function blankForm() {
  return {
    id: '',
    name: '',
    description: '',
    category: 'personal',
    enabled: true,
    type: 'semantic',
    keywords: [],
    pattern: '',
    valuePattern: '',
    scope: 'after',
    maxLen: 60,
    redactMode: 'rect',
    confidence: 0.85,
    protectSeal: false,
    columnHeaders: [],
    rowKeywords: [],
    valuePositions: ['right', 'same'],
    detect: 'id_card',
    excludeContext: [],
    skipPageKeywords: [],
    whitelist: []
  }
}

const selected = computed(
  () => versions.value.find((item) => item.id === selectedId.value) || detail.value?.version || null
)
const isDraft = computed(() => detail.value?.version?.status === 'draft')
const readonly = computed(() => !isDraft.value)
const statusMeta = computed(() => STATUS[selected.value?.status] || { text: selected.value?.status || '-', type: 'info' })


const stats = computed(() => ({
  total: rules.value.length,
  enabled: rules.value.filter((item) => item.enabled !== false).length,
  personal: rules.value.filter((item) => item._cat === 'personal').length,
  secret: rules.value.filter((item) => item._cat === 'secret').length,
  contact: rules.value.filter((item) => item._cat === 'contact').length
}))

const filteredRules = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return rules.value.filter((rule) => {
    if (categoryFilter.value !== 'all' && rule._cat !== categoryFilter.value) return false
    if (typeFilter.value !== 'all' && (rule.match?.type || 'semantic') !== typeFilter.value) return false
    if (!keyword) return true
    const haystack = [
      rule.id,
      rule.name,
      rule.description,
      ...ruleKeywords(rule),
      rule.match?.pattern,
      rule.match?.value_pattern
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return haystack.includes(keyword)
  })
})

const groupedRules = computed(() =>
  CATEGORIES.map((category) => ({
    ...category,
    rules: filteredRules.value.filter((rule) => rule._cat === category.key)
  })).filter((group) => group.rules.length)
)

const previewSegments = computed(() => {
  const text = previewText.value || ''
  if (!text) return []
  if (form.type === 'semantic') {
    const keywords = form.keywords.filter(Boolean)
    if (!keywords.length) return [{ text, hit: false }]
    return splitByPattern(text, new RegExp(`(${keywords.map(escapeRegExp).join('|')})`, 'g'))
  }
  if (form.type === 'regex' && form.pattern.trim()) {
    try {
      return splitByPattern(text, new RegExp(form.pattern, 'g'))
    } catch {
      return [{ text, hit: false }]
    }
  }
  return [{ text, hit: false }]
})
const previewHitCount = computed(() => previewSegments.value.filter((item) => item.hit).length)

function blankFormCopy() {
  return blankForm()
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function flattenRules(source) {
  const out = []
  for (const category of CATEGORIES) {
    for (const rule of source?.[category.key] || []) {
      out.push({
        ...rule,
        enabled: rule.enabled !== false,
        _cat: category.key,
        category: rule.category || category.key
      })
    }
  }
  return out
}

function buildPayload() {
  const next = clone(payload.value || {})
  for (const category of CATEGORIES) {
    next[category.key] = rules.value
      .filter((rule) => rule._cat === category.key)
      .map((rule) => {
        const copy = { ...rule }
        delete copy._cat
        return copy
      })
  }
  return next
}

function applyDetail(data) {
  detail.value = data
  payload.value = clone(data.payload || {})
  rules.value = flattenRules(payload.value)
  jsonText.value = JSON.stringify(payload.value, null, 2)
  yamlText.value = data.yaml || ''
  lastRawTab.value = rawTab.value
  validationErrors.value = []
}

function statusOf(row) {
  return STATUS[row?.status] || { text: row?.status || '-', type: 'info' }
}



function ruleKeywords(rule) {
  const match = rule.match || {}
  return [...(match.keywords || []), ...(match.row_keywords || []), ...(match.column_headers || [])].filter(Boolean)
}

function ruleDescription(rule) {
  if (rule.description) return rule.description
  const match = rule.match || {}
  const keywords = ruleKeywords(rule)
  if (match.type === 'semantic') {
    return keywords.length
      ? `当文中出现「${keywords.slice(0, 4).join('、')}」时，识别其后的内容并遮挡。`
      : '按关键词识别文本并遮挡。'
  }
  if (match.type === 'regex') return `识别${rule.name}，按固定格式匹配并遮挡。`
  if (match.type === 'table') {
    const labels = [...(match.column_headers || []), ...(match.row_keywords || [])]
    return labels.length ? `在表格中识别「${labels.slice(0, 3).join('、')}」对应的单元格。` : '在表格中识别指定列或行并遮挡。'
  }
  if (match.type === 'image') return '识别身份证、人脸等图片区域并遮挡。'
  return '按规则识别敏感信息并遮挡。'
}

function fmt(value) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 19)
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function splitByPattern(text, pattern) {
  const out = []
  let last = 0
  let match
  while ((match = pattern.exec(text))) {
    if (match.index > last) out.push({ text: text.slice(last, match.index), hit: false })
    out.push({ text: match[0], hit: true })
    last = match.index + match[0].length
    if (match.index === pattern.lastIndex) pattern.lastIndex += 1
  }
  if (last < text.length) out.push({ text: text.slice(last), hit: false })
  return out.length ? out : [{ text, hit: false }]
}

async function loadVersions() {
  versions.value = await request('/admin/rules/versions')
  if (!selectedId.value || !versions.value.some((item) => item.id === selectedId.value)) {
    const active = versions.value.find((item) => item.status === 'active')
    selectedId.value = active?.id || versions.value[0]?.id || null
  }
}

async function loadDetail() {
  if (!selectedId.value) return
  loading.value = true
  try {
    const data = await request(`/admin/rules/versions/${selectedId.value}`)
    applyDetail(data)
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

async function refresh() {
  try {
    await loadVersions()
    await loadDetail()
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function ensureDraft() {
  if (isDraft.value) return true
  const existing = versions.value.find((item) => item.status === 'draft')
  if (existing) {
    selectedId.value = existing.id
    await loadDetail()
    ElMessage.info(`已切换到草稿 v${existing.version}`)
    return true
  }
  if (actionLoading.value) return false
  actionLoading.value = true
  try {
    const data = await request('/admin/rules/versions', {
      method: 'POST',
      json: { note: `从 ${detail.value?.version?.version || '当前版本'} 创建` }
    })
    await loadVersions()
    selectedId.value = data.version.id
    await loadDetail()
    ElMessage.success(`已创建草稿 ${data.version.version}`)
    return true
  } catch (err) {
    ElMessage.error(err.message)
    return false
  } finally {
    actionLoading.value = false
  }
}

async function createDraft() {
  const created = await ensureDraft()
  if (created) await openNewRule()
}

async function persistRules(message = '已保存') {
  if (!isDraft.value) return false
  actionLoading.value = true
  try {
    const content = JSON.stringify(buildPayload(), null, 2)
    const data = await request(`/admin/rules/versions/${selectedId.value}`, {
      method: 'PUT',
      json: { format: 'json', content }
    })
    applyDetail(data)
    ElMessage.success(message)
    return true
  } catch (err) {
    ElMessage.error(err.message)
    return false
  } finally {
    actionLoading.value = false
  }
}

function resetForm(rule = null) {
  Object.assign(form, blankFormCopy())
  if (!rule) {
    form.id = nextRuleId()
    return
  }
  const match = rule.match || {}
  Object.assign(form, {
    id: rule.id,
    name: rule.name || '',
    description: rule.description || '',
    category: rule._cat || rule.category || 'personal',
    enabled: rule.enabled !== false,
    type: match.type || 'semantic',
    keywords: [...(match.keywords || [])],
    pattern: match.pattern || '',
    valuePattern: match.value_pattern || '',
    scope: match.scope || 'after',
    maxLen: match.max_len || 60,
    redactMode: rule.redact?.mode || 'rect',
    confidence: rule.confidence ?? 0.85,
    protectSeal: Boolean(rule.protect_seal),
    columnHeaders: [...(match.column_headers || [])],
    rowKeywords: [...(match.row_keywords || [])],
    valuePositions: [...(match.value_positions || [match.value_position || 'right'])],
    detect: match.detect || 'id_card',
    excludeContext: [...(match.exclude_context || [])],
    skipPageKeywords: [...(rule.skip_page_keywords || [])],
    whitelist: [...(match.whitelist || [])]
  })
}

function nextRuleId() {
  const used = new Set(rules.value.map((item) => item.id))
  let index = 1
  while (used.has(`LOCAL-${String(index).padStart(2, '0')}`)) index += 1
  return `LOCAL-${String(index).padStart(2, '0')}`
}

function resetDrawerScroll() {
  nextTick(() => {
    const body = document.querySelector('.el-drawer__body')
    if (body) body.scrollTop = 0
  })
}

async function openNewRule() {
  if (!(await ensureDraft())) return
  editingId.value = null
  resetForm()
  advancedPanels.value = []
  drawer.value = true
}

async function openEditRule(rule) {
  if (!(await ensureDraft())) return
  const fresh = rules.value.find((item) => item.id === rule.id)
  if (!fresh) return
  editingId.value = fresh.id
  resetForm(fresh)
  advancedPanels.value = []
  drawer.value = true
}

function buildRule() {
  const match = { type: form.type, on: 'auto' }
  if (form.type === 'semantic') {
    match.keywords = [...form.keywords]
    match.scope = form.scope
    match.max_len = Number(form.maxLen) || 60
    match.whitelist = []
    if (form.valuePattern.trim()) match.value_pattern = form.valuePattern.trim()
  } else if (form.type === 'regex') {
    match.pattern = form.pattern.trim()
  } else if (form.type === 'table') {
    if (form.columnHeaders.length) match.column_headers = [...form.columnHeaders]
    if (form.rowKeywords.length) match.row_keywords = [...form.rowKeywords]
    if (form.valuePositions.length) match.value_positions = [...form.valuePositions]
    if (form.valuePattern.trim()) match.value_pattern = form.valuePattern.trim()
  } else if (form.type === 'image') {
    match.detect = form.detect
  }
  if (form.excludeContext.length) match.exclude_context = [...form.excludeContext]
  if (form.whitelist.length) match.whitelist = [...form.whitelist]

  const redactMeta = REDACT_MODES.find((item) => item.value === form.redactMode) || REDACT_MODES[0]
  const rule = {
    id: form.id.trim(),
    name: form.name.trim(),
    enabled: form.enabled,
    category: form.category,
    confidence: Number(form.confidence) || 0.85,
    protect_seal: form.protectSeal,
    match,
    redact: { mode: form.redactMode, scope: redactMeta.scope }
  }
  if (form.description.trim()) rule.description = form.description.trim()
  if (form.skipPageKeywords.length) rule.skip_page_keywords = [...form.skipPageKeywords]
  return rule
}

function validateRule() {
  if (!form.name.trim()) return '请填写规则名称'
  if (!/^[A-Za-z][A-Za-z0-9-]{1,31}$/.test(form.id.trim())) return '规则 ID 需以字母开头，只包含字母、数字和横线'
  if (rules.value.some((item) => item.id === form.id.trim() && item.id !== editingId.value)) return '规则 ID 已存在'
  if (form.type === 'semantic' && !form.keywords.length) return '请至少添加一个关键词'
  if (form.type === 'regex') {
    if (!form.pattern.trim()) return '请填写正则表达式'
    try {
      new RegExp(form.pattern)
    } catch {
      return '正则表达式格式不正确'
    }
  }
  if (form.type === 'table' && !form.columnHeaders.length && !form.rowKeywords.length) {
    return '表格规则至少填写一个列名或行标签'
  }
  if (form.valuePattern.trim()) {
    try {
      new RegExp(form.valuePattern)
    } catch {
      return '值格式正则表达式不正确'
    }
  }
  return ''
}

async function saveRule() {
  const error = validateRule()
  if (error) {
    ElMessage.warning(error)
    return
  }
  const rule = buildRule()
  const item = { ...rule, _cat: form.category, category: form.category }
  const previous = clone(rules.value)
  const index = editingId.value ? rules.value.findIndex((entry) => entry.id === editingId.value) : -1
  if (index >= 0) rules.value.splice(index, 1, item)
  else rules.value.push(item)
  const saved = await persistRules(editingId.value ? '规则已更新' : '规则已添加')
  if (saved) {
    editingId.value = null
    drawer.value = false
  } else {
    rules.value = previous
  }
}

async function toggleRule(rule) {
  if (readonly.value) return
  const before = !rule.enabled
  const saved = await persistRules(rule.enabled ? '规则已启用' : '规则已停用')
  if (!saved) rule.enabled = before
}

async function removeRule() {
  if (!editingId.value) return
  try {
    await ElMessageBox.confirm('删除后需要重新发布才会影响新文件，确定删除这条规则吗？', '删除规则', {
      type: 'warning'
    })
    const previous = clone(rules.value)
    rules.value = rules.value.filter((item) => item.id !== editingId.value)
    const saved = await persistRules('规则已删除')
    if (saved) {
      editingId.value = null
      drawer.value = false
    } else {
      rules.value = previous
    }
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '删除失败')
  }
}

async function publish() {
  if (!isDraft.value) return
  actionLoading.value = true
  try {
    const content = JSON.stringify(buildPayload(), null, 2)
    const result = await request(`/admin/rules/versions/${selectedId.value}/validate`, {
      method: 'POST',
      json: { format: 'json', content }
    })
    if (!result.valid) {
      validationErrors.value = result.errors || []
      ElMessage.warning('校验未通过，请先处理错误')
      return
    }
    await ElMessageBox.confirm(
      `发布 v${detail.value.version.version} 后，新上传文件将使用这套规则；已有文件保留原规则版本。`,
      '发布规则',
      { type: 'warning' }
    )
    await request(`/admin/rules/versions/${selectedId.value}/activate`, { method: 'POST' })
    await refresh()
    ElMessage.success('已发布为生效版本')
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '发布失败')
  } finally {
    actionLoading.value = false
  }
}

async function rollbackVersion(row) {
  try {
    await ElMessageBox.confirm(`将版本 ${row.version} 复制为新的生效版本？当前生效版本将归档。`, '版本回滚', {
      type: 'warning'
    })
    actionLoading.value = true
    await request(`/admin/rules/versions/${row.id}/rollback`, { method: 'POST' })
    await refresh()
    ElMessage.success('已回滚并生成新的生效版本')
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '回滚失败')
  } finally {
    actionLoading.value = false
  }
}

async function exportYaml(row) {
  try {
    await exportRulesYaml(row.id, row.version)
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function saveRaw() {
  if (!isDraft.value) return
  rawLoading.value = true
  try {
    const content = rawTab.value === 'json' ? jsonText.value : yamlText.value
    const data = await request(`/admin/rules/versions/${selectedId.value}`, {
      method: 'PUT',
      json: { format: rawTab.value, content }
    })
    applyDetail(data)
    ElMessage.success('高级模式已保存')
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    rawLoading.value = false
  }
}

async function validateRaw() {
  actionLoading.value = true
  try {
    const content = rawTab.value === 'json' ? jsonText.value : yamlText.value
    const result = await request(`/admin/rules/versions/${selectedId.value}/validate`, {
      method: 'POST',
      json: { format: rawTab.value, content }
    })
    validationErrors.value = result.errors || []
    if (result.valid) ElMessage.success('校验通过')
    else ElMessage.warning('校验未通过，请查看错误列表')
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    actionLoading.value = false
  }
}

async function onRawTabChange(name) {
  const previous = lastRawTab.value
  if (name === previous) return
  try {
    const content = name === 'yaml' ? jsonText.value : yamlText.value
    const converted = await request('/admin/rules/convert', {
      method: 'POST',
      json: { format: name === 'yaml' ? 'json' : 'yaml', content }
    })
    if (name === 'yaml') yamlText.value = converted.content
    else jsonText.value = converted.content
    lastRawTab.value = name
  } catch (err) {
    rawTab.value = previous
    ElMessage.error(err.message)
  }
}

async function doImport() {
  if (!importText.value.trim()) {
    ElMessage.warning('请粘贴 YAML 内容')
    return
  }
  actionLoading.value = true
  try {
    const data = await request('/admin/rules/import', {
      method: 'POST',
      json: { yaml: importText.value, version: importVersion.value || undefined }
    })
    importDialog.value = false
    importText.value = ''
    importVersion.value = ''
    await loadVersions()
    selectedId.value = data.version.id
    await loadDetail()
    ElMessage.success(`已导入为草稿 ${data.version.version}`)
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    actionLoading.value = false
  }
}

function onVersionChange() {
  loadDetail()
}

function selectVersion(row) {
  selectedId.value = row.id
  loadDetail()
}

onMounted(refresh)
</script>

<template>
  <div class="rules-workbench">
    <div v-if="!embedded" class="page-title">
      <div>
        <h2>规则库</h2>
        <p class="page-subtitle">用规则清单管理“识别什么、怎么遮挡”，不懂代码也能查看和新增关键词。</p>
      </div>
      <el-button :icon="ArrowDown" @click="refresh">刷新</el-button>
    </div>

    <div v-if="detail" class="version-banner">
      <div class="version-main">
        <div class="meta-row">
          <el-select v-model="selectedId" style="width: 190px" @change="onVersionChange">
            <el-option
              v-for="item in versions"
              :key="item.id"
              :value="item.id"
              :label="`v${item.version} · ${statusOf(item).text}`"
            />
          </el-select>
          <el-tag :type="statusMeta.type" effect="light">{{ statusMeta.text }}</el-tag>
          <span class="rule-id">v{{ detail.version.version }}</span>
        </div>
        <p>
          <template v-if="readonly">当前是只读版本。创建草稿后可以新增规则、修改关键词和启停。</template>
          <template v-else>草稿修改不会影响线上文件；发布后只作用于新上传文件。</template>
        </p>
      </div>
      <div class="toolbar">
        <el-button v-if="readonly" type="primary" :loading="actionLoading" @click="createDraft">
          创建草稿并编辑
        </el-button>
        <el-button v-else type="primary" :icon="Plus" @click="openNewRule">新建规则</el-button>
        <el-button v-if="isDraft" type="success" :loading="actionLoading" @click="publish">发布</el-button>
        <el-dropdown trigger="click">
          <el-button :icon="MoreFilled">更多</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="exportYaml(selected)">导出 YAML</el-dropdown-item>
              <el-dropdown-item @click="importDialog = true">导入 YAML</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <div class="rules-stats">
      <div class="stat-card">
        <div class="label">规则总数</div>
        <div class="value">{{ stats.total }}</div>
      </div>
      <div class="stat-card">
        <div class="label">已启用</div>
        <div class="value">{{ stats.enabled }}</div>
      </div>
      <div class="stat-card">
        <div class="label">个人隐私</div>
        <div class="value">{{ stats.personal }}</div>
      </div>
      <div class="stat-card">
        <div class="label">商业秘密</div>
        <div class="value">{{ stats.secret }}</div>
      </div>
      <div class="stat-card">
        <div class="label">企业联系</div>
        <div class="value">{{ stats.contact }}</div>
      </div>
    </div>

    <div class="rules-toolbar">
      <el-input
        v-model="search"
        :prefix-icon="Search"
        placeholder="搜索规则名称、ID、关键词"
        clearable
        class="rule-search"
      />
      <div class="filter-chips">
        <button
          type="button"
          class="filter-chip"
          :class="{ active: categoryFilter === 'all' }"
          @click="categoryFilter = 'all'"
        >
          全部
        </button>
        <button
          v-for="category in CATEGORIES"
          :key="category.key"
          type="button"
          class="filter-chip"
          :class="{ active: categoryFilter === category.key }"
          @click="categoryFilter = category.key"
        >
          {{ category.label }}
        </button>
      </div>
      <el-select v-model="typeFilter" style="width: 138px">
        <el-option label="全部方式" value="all" />
        <el-option v-for="item in MATCH_TYPES" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
    </div>

    <div v-if="validationErrors.length" class="card validation-card">
      <el-alert type="error" :closable="false" show-icon title="校验未通过">
        <div v-for="(item, index) in validationErrors" :key="index" class="mono">{{ index + 1 }}. {{ item }}</div>
      </el-alert>
    </div>

    <div class="card rule-list-card" v-loading="loading">
      <div class="rule-list-head">
        <span>规则清单</span>
        <span class="muted">{{ filteredRules.length }} 条</span>
      </div>
      <div v-if="filteredRules.length">
        <template v-for="group in groupedRules" :key="group.key">
          <div class="rule-group-head">
            <span>{{ group.label }}</span>
            <span class="muted">{{ group.rules.length }} 条</span>
          </div>
          <div v-for="rule in group.rules" :key="rule.id" class="rule-row">
            <div class="rule-row-inner">
              <div class="rule-main" @click="openEditRule(rule)">
                <div class="rule-name">
                  {{ rule.name }}
                  <el-tag v-if="rule.enabled === false" type="info" size="small" effect="light">已停用</el-tag>
                </div>
                <p class="rule-desc">{{ ruleDescription(rule) }}</p>
                <div v-if="ruleKeywords(rule).length" class="tag-list rule-keywords">
                  <el-tag v-for="keyword in ruleKeywords(rule).slice(0, 8)" :key="keyword" size="small" effect="plain">
                    {{ keyword }}
                  </el-tag>
                  <span v-if="ruleKeywords(rule).length > 8" class="more-keywords">+{{ ruleKeywords(rule).length - 8 }}</span>
                </div>
              </div>
              <div class="rule-actions">
                <el-switch
                  v-model="rule.enabled"
                  :disabled="readonly"
                  size="small"
                  @change="toggleRule(rule)"
                />
                <el-button text :icon="EditPen" @click.stop="openEditRule(rule)">编辑</el-button>
              </div>
            </div>
          </div>
        </template>
      </div>
      <div v-else class="empty-state">
        <strong>没有匹配的规则</strong>
        <span>换个关键词，或清除分类筛选。</span>
      </div>
    </div>

    <el-collapse v-model="bottomPanels" class="bottom-panels">
      <el-collapse-item title="版本记录" name="versions">
        <el-table :data="versions" size="small" stripe style="cursor: pointer" @row-click="selectVersion">
          <el-table-column label="版本" width="100">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusOf(row).type" size="small" effect="light">{{ statusOf(row).text }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="rule_count" label="规则数" width="86" />
          <el-table-column prop="note" label="说明" min-width="220" show-overflow-tooltip />
          <el-table-column label="创建时间" width="170">
            <template #default="{ row }">{{ fmt(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button link type="primary" @click.stop="exportYaml(row)">导出</el-button>
              <el-button v-if="row.status !== 'active'" link type="warning" @click.stop="rollbackVersion(row)">回滚</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>

      <el-collapse-item title="高级模式：JSON / YAML" name="raw">
        <p class="field-help" style="margin-bottom: 12px">
          只有维护规则库的技术人员需要使用。普通编辑请在规则清单中点“编辑”。
        </p>
        <div class="toolbar" style="margin-bottom: 10px">
          <el-radio-group v-model="rawTab" @change="onRawTabChange">
            <el-radio-button label="json">JSON</el-radio-button>
            <el-radio-button label="yaml">YAML</el-radio-button>
          </el-radio-group>
          <div class="toolbar-spacer"></div>
          <el-button :loading="actionLoading" @click="validateRaw">校验</el-button>
          <el-button type="primary" :disabled="readonly" :loading="rawLoading" @click="saveRaw">保存高级修改</el-button>
        </div>
        <el-input
          v-if="rawTab === 'json'"
          v-model="jsonText"
          type="textarea"
          :rows="18"
          class="mono"
          :readonly="readonly"
          spellcheck="false"
        />
        <el-input
          v-else
          v-model="yamlText"
          type="textarea"
          :rows="18"
          class="mono"
          :readonly="readonly"
          spellcheck="false"
        />
      </el-collapse-item>
    </el-collapse>

    <el-drawer
      v-model="drawer"
      :title="editingId ? '编辑规则' : '新建规则'"
      size="560px"
      append-to-body
      destroy-on-close
      @opened="resetDrawerScroll"
    >
      <el-form label-position="top" class="rule-form">
        <div class="drawer-section">
          <el-form-item label="规则名称" required>
            <el-input v-model="form.name" placeholder="例如：证书编号" maxlength="40" />
          </el-form-item>
          <div class="form-grid">
            <el-form-item label="规则 ID">
              <el-input v-model="form.id" placeholder="例如：LOCAL-01" />
            </el-form-item>
            <el-form-item label="分类">
              <el-select v-model="form.category">
                <el-option v-for="category in CATEGORIES" :key="category.key" :label="category.label" :value="category.key" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="一句话说明（可选）">
            <el-input v-model="form.description" placeholder="用普通用户能看懂的话说明这条规则保护什么" />
          </el-form-item>
          <el-form-item label="启用这条规则">
            <el-switch v-model="form.enabled" />
          </el-form-item>
        </div>

        <div class="drawer-section">
          <h4 class="drawer-title">识别方式</h4>
          <el-radio-group v-model="form.type" :disabled="readonly" class="type-switch">
            <el-radio-button v-for="item in MATCH_TYPES" :key="item.value" :label="item.value">
              {{ item.label }}
            </el-radio-button>
          </el-radio-group>

          <template v-if="form.type === 'semantic'">
            <el-form-item label="关键词" required style="margin-top: 18px">
              <TagEditor v-model="form.keywords" :disabled="readonly" placeholder="输入关键词后按回车，例如：证书编号" />
              <div class="field-help">当文中出现这些词时，识别其后的内容并遮挡。可一次粘贴多个关键词，用逗号分隔。</div>
            </el-form-item>
            <div class="form-grid">
              <el-form-item label="识别范围">
                <el-select v-model="form.scope" :disabled="readonly">
                  <el-option label="关键词之后的内容" value="after" />
                  <el-option label="整段文字" value="block" />
                </el-select>
              </el-form-item>
              <el-form-item label="最多识别长度">
                <el-input-number v-model="form.maxLen" :min="10" :max="300" :disabled="readonly" controls-position="right" />
              </el-form-item>
            </div>
            <el-form-item label="值格式（高级，可选）">
              <el-input v-model="form.valuePattern" :disabled="readonly" class="mono" placeholder="例如：[A-Za-z0-9\\-]{6,}" />
              <div class="field-help">留空则取关键词后的整段文字；填写正则可只取号码部分。</div>
            </el-form-item>
          </template>

          <template v-if="form.type === 'regex'">
            <el-form-item label="正则表达式" required style="margin-top: 18px">
              <el-input v-model="form.pattern" :disabled="readonly" class="mono" placeholder="例如：(?<!\\d)1[3-9]\\d{9}(?!\\d)" />
              <div class="field-help">适合固定格式的手机号、身份证号、证书编号等。</div>
            </el-form-item>
          </template>

          <template v-if="form.type === 'table'">
            <el-form-item label="列名关键词" style="margin-top: 18px">
              <TagEditor v-model="form.columnHeaders" :disabled="readonly" placeholder="例如：证号、联系电话" />
            </el-form-item>
            <el-form-item label="行标签关键词">
              <TagEditor v-model="form.rowKeywords" :disabled="readonly" placeholder="例如：证书编号、注册编号" />
            </el-form-item>
            <el-form-item label="值所在位置">
              <el-checkbox-group v-model="form.valuePositions" :disabled="readonly">
                <el-checkbox label="right">同一行右侧</el-checkbox>
                <el-checkbox label="below">下一行</el-checkbox>
                <el-checkbox label="same">同一单元格</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item label="值格式（可选）">
              <el-input v-model="form.valuePattern" :disabled="readonly" class="mono" placeholder="留空默认识别数字" />
            </el-form-item>
          </template>

          <template v-if="form.type === 'image'">
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="图片规则需要视觉模型配合"
              description="当前支持身份证、人脸等图片区域。新增图片规则后，建议上传真实文件验证效果。"
              style="margin-top: 18px"
            />
          </template>
        </div>

        <div class="drawer-section">
          <h4 class="drawer-title">遮挡方式</h4>
          <div class="form-grid">
            <el-form-item label="遮挡范围">
              <el-select v-model="form.redactMode" :disabled="readonly">
                <el-option v-for="item in REDACT_MODES" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="置信度">
              <el-slider v-model="form.confidence" :min="0.5" :max="1" :step="0.01" :disabled="readonly" />
            </el-form-item>
          </div>
          <el-form-item label="遇到红色公章时保留">
            <el-switch v-model="form.protectSeal" :disabled="readonly" />
            <span class="field-help" style="margin-left: 10px">开启后，与红色公章重叠时跳过这条规则。</span>
          </el-form-item>
        </div>

        <el-collapse v-model="advancedPanels" class="drawer-advanced">
          <el-collapse-item title="高级设置" name="advanced">
            <el-form-item label="排除上下文关键词">
              <TagEditor v-model="form.excludeContext" :disabled="readonly" placeholder="出现这些词时不触发，例如：身份证" />
            </el-form-item>
            <el-form-item label="跳过页面关键词">
              <TagEditor v-model="form.skipPageKeywords" :disabled="readonly" placeholder="页面出现这些词时整页跳过，例如：投标函" />
            </el-form-item>
            <el-form-item label="白名单引用（高级）">
              <TagEditor v-model="form.whitelist" :disabled="readonly" placeholder="例如：WL-07" />
            </el-form-item>
          </el-collapse-item>
        </el-collapse>

        <div class="drawer-section preview-section">
          <div class="toolbar" style="margin-bottom: 10px">
            <h4 class="drawer-title" style="margin: 0">试跑这段话</h4>
            <div class="toolbar-spacer"></div>
            <el-tag :type="previewHitCount ? 'success' : 'info'" effect="light">命中 {{ previewHitCount }} 处</el-tag>
          </div>
          <el-input v-model="previewText" type="textarea" :rows="3" placeholder="粘贴一段文本，看看关键词能不能命中" />
          <p class="preview-text">
            <span v-for="(part, index) in previewSegments" :key="index" :class="{ hit: part.hit }">{{ part.text }}</span>
          </p>
          <p v-if="form.type === 'table' || form.type === 'image'" class="field-help">
            表格和图片规则需要在真实文件中验证；发布前请用文件列表里的“重新处理”看效果。
          </p>
        </div>
      </el-form>

      <template #footer>
        <div class="drawer-footer">
          <el-button v-if="editingId" type="danger" text :icon="Delete" @click="removeRule">删除规则</el-button>
          <div class="toolbar-spacer"></div>
          <el-button @click="drawer = false">取消</el-button>
          <el-button type="primary" :loading="actionLoading" @click="saveRule">保存规则</el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="importDialog" title="导入 YAML" width="720px">
      <el-form label-width="90px">
        <el-form-item label="新版本号">
          <el-input v-model="importVersion" placeholder="留空自动生成，例如 1.5" style="width: 220px" />
        </el-form-item>
        <el-form-item label="YAML">
          <el-input v-model="importText" type="textarea" :rows="18" class="mono" spellcheck="false" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importDialog = false">取消</el-button>
        <el-button type="primary" :loading="actionLoading" @click="doImport">导入为草稿</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.rules-workbench {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.rules-workbench :deep(.el-drawer) {
  max-width: 94vw;
}

.version-banner {
  margin-bottom: 0;
}

.version-main {
  min-width: 0;
}

.version-main p {
  margin: 8px 0 0;
  color: var(--ink-500);
  font-size: 13px;
}

.rules-stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.rules-stats .stat-card {
  padding: 13px 15px;
}

.rules-stats .stat-card .value {
  font-size: 22px;
  margin-top: 4px;
}

.rules-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.rule-search {
  width: 300px;
}

.filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.filter-chip {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-500);
  border-radius: 999px;
  padding: 7px 13px;
  font: inherit;
  font-size: 12px;
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

.rule-list-card {
  padding: 0;
  overflow: hidden;
}

.rule-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
  color: var(--ink-700);
  font-size: 13px;
  font-weight: 650;
}

.rule-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 18px;
  background: var(--surface-muted);
  border-bottom: 1px solid var(--line);
  color: var(--ink-500);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.rule-main {
  min-width: 0;
  cursor: pointer;
}

.rule-keywords {
  margin-top: 10px;
}

.more-keywords {
  align-self: center;
  color: var(--ink-400);
  font-size: 11px;
}

.rule-actions {
  align-items: center;
  padding-top: 2px;
}

.validation-card {
  padding: 12px;
}

.bottom-panels {
  border: 0;
}

.bottom-panels :deep(.el-collapse-item__header) {
  background: transparent;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-700);
  border-bottom: 1px solid var(--line);
}

.bottom-panels :deep(.el-collapse-item__wrap) {
  background: transparent;
  border-bottom: 1px solid var(--line);
}

.bottom-panels :deep(.el-collapse-item__content) {
  padding: 16px 0 20px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.drawer-section {
  padding: 18px 0;
  border-top: 1px solid var(--line);
}

.drawer-section:first-child {
  border-top: 0;
  padding-top: 0;
}

.drawer-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 650;
  color: var(--ink-900);
}

.type-switch {
  width: 100%;
}

.type-switch :deep(.el-radio-button) {
  flex: 1;
}

.type-switch :deep(.el-radio-button__inner) {
  width: 100%;
}

.drawer-advanced {
  margin: 4px 0 0;
}

.preview-section {
  margin-top: 4px;
}

.preview-text {
  margin: 12px 0 0;
  padding: 12px 14px;
  min-height: 58px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  color: var(--ink-700);
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
}

.preview-text .hit {
  background: #fde7b0;
  color: #6b3d00;
  border-radius: 3px;
  padding: 1px 2px;
}

.drawer-footer {
  display: flex;
  align-items: center;
  width: 100%;
}

@media (max-width: 980px) {
  .rules-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .rule-search {
    width: 100%;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .version-banner {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>