const BASE = '/api'
const TOKEN_KEY = 'bidredact_token'
const USER_KEY = 'bidredact_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user || null))
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

function authHeaders(extra = {}) {
  const headers = { ...extra }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

async function errorMessage(res) {
  try {
    const data = await res.json()
    return data.detail || data.message || `请求失败（${res.status}）`
  } catch {
    return `请求失败（${res.status}）`
  }
}

export async function request(path, { method = 'GET', json, body, headers } = {}) {
  const options = { method, headers: authHeaders(headers) }
  if (json !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(json)
  } else if (body !== undefined) {
    options.body = body
  }

  const res = await fetch(BASE + path, options)
  if (res.status === 401) {
    clearAuth()
    if (location.pathname !== '/login') location.href = '/login'
    throw new Error('登录已过期')
  }
  if (!res.ok) throw new Error(await errorMessage(res))
  const type = res.headers.get('content-type') || ''
  return type.includes('application/json') ? res.json() : res
}

export async function requestBlob(path) {
  const res = await request(path)
  return res.blob()
}

export function login(account, password) {
  return request('/auth/login', { method: 'POST', json: { account, password } })
}

export function register(payload) {
  return request('/auth/register', { method: 'POST', json: payload })
}

export function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/files`)
    xhr.setRequestHeader('Authorization', `Bearer ${getToken()}`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText))
        } catch {
          reject(new Error('上传响应解析失败'))
        }
        return
      }
      let message = `上传失败（${xhr.status}）`
      try {
        message = JSON.parse(xhr.responseText).detail || message
      } catch {}
      reject(new Error(message))
    }
    xhr.onerror = () => reject(new Error('上传失败，请检查网络'))
    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}

export async function downloadRedacted(id, filename) {
  const res = await fetch(`${BASE}/files/${id}/download`, {
    headers: authHeaders()
  })
  if (!res.ok) throw new Error(await errorMessage(res))
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename || `脱敏文件_${id}.pdf`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function previewUrl(id, page, dpi = 150) {
  return requestBlob(`/files/${id}/preview/${page}?dpi=${dpi}`)
}

export async function downloadPath(path, filename) {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (!res.ok) throw new Error(await errorMessage(res))
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function exportRulesYaml(id, version) {
  return downloadPath(`/admin/rules/versions/${id}/export`, `rules-${version || id}.yaml`)
}