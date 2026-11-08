<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, register, setAuth } from '../api'

const router = useRouter()
const route = useRoute()
const mode = ref('login')
const loading = ref(false)

const loginForm = reactive({ account: '', password: '' })
const registerForm = reactive({ username: '', email: '', password: '', confirm: '' })

async function submitLogin() {
  if (!loginForm.account.trim() || !loginForm.password) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  loading.value = true
  try {
    const data = await login(loginForm.account.trim(), loginForm.password)
    setAuth(data.access_token, data.user)
    router.replace(route.query.redirect || '/files')
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

async function submitRegister() {
  if (!registerForm.username.trim()) {
    ElMessage.warning('请输入用户名')
    return
  }
  if (registerForm.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  if (registerForm.password !== registerForm.confirm) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  loading.value = true
  try {
    const data = await register({
      username: registerForm.username.trim(),
      email: registerForm.email.trim() || null,
      password: registerForm.password
    })
    setAuth(data.access_token, data.user)
    ElMessage.success('注册成功')
    router.replace('/files')
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-brand">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3.2 19 6v5.4c0 4.2-2.8 7.6-7 9.4-4.2-1.8-7-5.2-7-9.4V6l7-2.8Z" />
            <path d="m9.2 12.1 1.8 1.8 3.8-3.9" />
          </svg>
        </span>
        <div>
          <div class="login-title">投标文件自动脱敏</div>
          <div class="login-sub">上传 PDF，自动定位并遮蔽敏感信息</div>
        </div>
      </div>

      <el-tabs v-model="mode" stretch>
        <el-tab-pane label="登录" name="login">
          <el-form label-position="top" @submit.prevent="submitLogin">
            <el-form-item label="用户名或邮箱">
              <el-input v-model="loginForm.account" autocomplete="username" placeholder="请输入用户名或邮箱" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="loginForm.password"
                type="password"
                show-password
                autocomplete="current-password"
                placeholder="请输入密码"
                @keyup.enter="submitLogin"
              />
            </el-form-item>
            <el-button type="primary" style="width: 100%" :loading="loading" @click="submitLogin">登录</el-button>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="注册" name="register">
          <el-form label-position="top" @submit.prevent="submitRegister">
            <el-form-item label="用户名">
              <el-input v-model="registerForm.username" placeholder="3-32 位字母、数字或下划线" />
            </el-form-item>
            <el-form-item label="邮箱（可选）">
              <el-input v-model="registerForm.email" placeholder="用于登录或找回密码" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="registerForm.password" type="password" show-password placeholder="至少 6 位" />
            </el-form-item>
            <el-form-item label="确认密码">
              <el-input
                v-model="registerForm.confirm"
                type="password"
                show-password
                placeholder="再次输入密码"
                @keyup.enter="submitRegister"
              />
            </el-form-item>
            <el-button type="primary" style="width: 100%" :loading="loading" @click="submitRegister">注册</el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
      <p class="login-foot">本地部署模式 · 登录用户拥有完整管理权限</p>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(900px 480px at 18% 8%, rgba(29, 79, 145, 0.1), transparent 58%),
    #f4f6f8;
}

.login-card {
  width: 430px;
  background: var(--surface);
  border-radius: var(--radius);
  padding: 30px 32px 22px;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--line);
  animation: page-rise 0.32s cubic-bezier(0.2, 0.7, 0.3, 1) both;
}

@media (prefers-reduced-motion: reduce) {
  .login-card {
    animation: none;
  }
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 22px;
}

.login-title {
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.login-sub {
  color: var(--ink-500);
  font-size: 13px;
  margin-top: 4px;
}

.login-foot {
  margin: 18px 0 0;
  text-align: center;
  color: var(--ink-400);
  font-size: 12px;
}
</style>