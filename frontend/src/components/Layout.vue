<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { clearAuth, getUser } from '../api'

const router = useRouter()
const route = useRoute()
const user = computed(() => getUser())
const active = computed(() => {
  if (route.path.startsWith('/admin')) return '/admin'
  if (route.path.startsWith('/upload')) return '/upload'
  return '/files'
})
const initial = computed(() => (user.value?.username || user.value?.email || '用').slice(0, 1).toUpperCase())

function logout() {
  clearAuth()
  ElMessage.success('已退出登录')
  router.replace('/login')
}
</script>

<template>
  <el-container>
    <el-header class="layout-header">
      <router-link to="/files" class="brand">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3.2 19 6v5.4c0 4.2-2.8 7.6-7 9.4-4.2-1.8-7-5.2-7-9.4V6l7-2.8Z" />
            <path d="m9.2 12.1 1.8 1.8 3.8-3.9" />
          </svg>
        </span>
        投标文件自动脱敏
      </router-link>
      <nav class="nav">
        <router-link to="/upload" :class="{ 'router-link-active': active === '/upload' }">上传文件</router-link>
        <router-link to="/files" :class="{ 'router-link-active': active === '/files' }">文件列表</router-link>
        <router-link v-if="user?.role === 'admin'" to="/admin" :class="{ 'router-link-active': active === '/admin' }">
          管理后台
        </router-link>
      </nav>
      <el-dropdown trigger="click">
        <span class="user-trigger">
          <span class="user-avatar">{{ initial }}</span>
          <span>{{ user?.username || user?.email || '用户' }}</span>
          <el-tag v-if="user?.role === 'admin'" size="small" type="primary">本地管理员</el-tag>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </el-header>
    <el-main class="layout-main">
      <router-view />
    </el-main>
  </el-container>
</template>