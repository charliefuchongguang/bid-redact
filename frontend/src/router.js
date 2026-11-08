import { createRouter, createWebHistory } from 'vue-router'
import { getToken, getUser } from './api'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/Login.vue') },
  {
    path: '/',
    component: () => import('./components/Layout.vue'),
    children: [
      { path: '', redirect: '/files' },
      { path: 'files', name: 'files', component: () => import('./views/Files.vue') },
      { path: 'upload', name: 'upload', component: () => import('./views/Upload.vue') },
      { path: 'files/:id', name: 'result', component: () => import('./views/Result.vue'), props: true },
      { path: 'admin', name: 'admin', component: () => import('./views/Admin.vue'), meta: { admin: true } }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/files' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to) => {
  const token = getToken()
  if (to.name !== 'login' && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.admin) {
    const user = getUser()
    if (!user || user.role !== 'admin') return { name: 'files' }
  }
  if (to.name === 'login' && token) return { name: 'files' }
  return true
})

export default router