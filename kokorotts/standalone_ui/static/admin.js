const $ = (selector) => document.querySelector(selector)
const languageNames = { a: 'Tiếng Anh (Mỹ)', b: 'Tiếng Anh (Anh)', j: 'Tiếng Nhật', z: 'Tiếng Trung', e: 'Tiếng Tây Ban Nha', f: 'Tiếng Pháp', h: 'Tiếng Hindi', i: 'Tiếng Ý', p: 'Tiếng Bồ Đào Nha (Brasil)', d: 'Tiếng Đức', v: 'Tiếng Việt' }
let csrfToken = ''
let enabledModels = []
let supportedModels = []

function message(selector, text = '', tone = 'error') {
  const element = $(selector)
  element.textContent = text
  element.dataset.tone = tone
  element.hidden = !text
}

async function request(path, { method = 'GET', body } = {}) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (!['GET', 'HEAD'].includes(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken
  const response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin', cache: 'no-store' })
  const payload = await response.json().catch(() => ({}))
  if (response.status === 401 && path !== '/admin/api/login') {
    window.location.assign('/admin/login')
    throw new Error('Phiên đăng nhập đã hết hạn.')
  }
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Không thể hoàn tất yêu cầu. Vui lòng thử lại.')
  return payload
}

async function busy(button, operation) {
  button.disabled = true
  try {
    return await operation()
  } finally {
    button.disabled = false
  }
}

function selectedModels() {
  return [...$('#admin-model-groups').querySelectorAll('input:checked')].map((input) => input.value)
}

function updateSaveButton() {
  const selected = selectedModels()
  const unchanged = selected.length === enabledModels.length && selected.every((id) => enabledModels.includes(id))
  $('#admin-save-models').disabled = !selected.length || unchanged
}

function renderModels(payload) {
  enabledModels = payload.enabled
  supportedModels = payload.supported
  const container = $('#admin-model-groups')
  container.replaceChildren(...supportedModels.map((model) => {
    const label = document.createElement('label')
    label.className = 'admin-model-option'
    const checkbox = document.createElement('input')
    checkbox.type = 'checkbox'
    checkbox.name = 'model_families'
    checkbox.value = model.id
    checkbox.checked = enabledModels.includes(model.id)
    checkbox.addEventListener('change', () => {
      updateSaveButton()
      message('#admin-models-message', selectedModels().length ? '' : 'Phải giữ ít nhất một nhóm giọng.')
    })
    const copy = document.createElement('span')
    const name = document.createElement('strong')
    name.textContent = model.name
    const details = document.createElement('span')
    details.className = 'admin-model-description'
    details.textContent = `${model.voice_count} giọng · ${model.languages.map((language) => languageNames[language.code] || language.name).join(', ')}`
    copy.append(name, details)
    label.append(checkbox, copy)
    return label
  }))
  updateSaveButton()
}

async function refreshStatus() {
  const status = await request('/admin/api/status')
  $('#admin-service-state').textContent = 'Đang hoạt động'
  $('#admin-device').textContent = status.runtime
  $('#admin-voice-count').textContent = status.voices
  $('#admin-model-count').textContent = status.loaded_models.length
  const list = $('#admin-loaded-models')
  list.replaceChildren(...status.loaded_models.map((model) => {
    const item = document.createElement('li')
    const family = supportedModels.find((entry) => entry.id === model.model_family)
    item.textContent = `${family?.name || model.model_family} · ${model.device}`
    return item
  }))
  if (!status.loaded_models.length) {
    const empty = document.createElement('li')
    empty.textContent = 'Chưa có model nào trong bộ nhớ.'
    list.append(empty)
  }
}

function bindLogin() {
  $('#admin-login-form').addEventListener('submit', async (event) => {
    event.preventDefault()
    message('#admin-login-error')
    try {
      await busy($('#admin-login-button'), () => request('/admin/api/login', {
        method: 'POST', body: { username: $('#admin-username').value.trim(), password: $('#admin-password').value },
      }))
      $('#admin-password').value = ''
      window.location.assign('/admin')
    } catch (error) {
      message('#admin-login-error', error.message || 'Không thể đăng nhập. Vui lòng thử lại.')
    }
  })
}

async function bindDashboard() {
  const session = await request('/admin/api/session')
  csrfToken = session.csrf_token
  $('#admin-session-name').textContent = session.username
  $('#admin-refresh').addEventListener('click', async (event) => {
    message('#admin-error')
    try {
      await busy(event.currentTarget, refreshStatus)
    } catch (error) {
      message('#admin-error', error.message)
    }
  })
  $('#admin-models-form').addEventListener('submit', async (event) => {
    event.preventDefault()
    message('#admin-models-message')
    try {
      await busy($('#admin-save-models'), async () => {
        const payload = await request('/admin/api/models', { method: 'PUT', body: { model_families: selectedModels() } })
        renderModels(payload)
        await refreshStatus()
        message('#admin-models-message', 'Đã lưu các nhóm giọng.', 'success')
      })
    } catch (error) {
      message('#admin-models-message', error.message)
    } finally {
      updateSaveButton()
    }
  })
  $('#admin-purge').addEventListener('click', async (event) => {
    message('#admin-purge-message')
    try {
      await busy(event.currentTarget, async () => {
        const result = await request('/admin/api/models/purge', { method: 'POST' })
        await refreshStatus()
        message('#admin-purge-message', result.purged.length ? 'Đã giải phóng model khỏi bộ nhớ.' : 'Chưa có model nào trong bộ nhớ.', 'success')
      })
    } catch (error) {
      message('#admin-purge-message', error.message)
    }
  })
  $('#admin-logout').addEventListener('click', async (event) => {
    try {
      await busy(event.currentTarget, () => request('/admin/api/logout', { method: 'POST' }))
      window.location.assign('/admin/login')
    } catch (error) {
      message('#admin-error', error.message)
    }
  })
  renderModels(await request('/admin/api/models'))
  await refreshStatus()
}

if (document.body.dataset.adminView === 'login') {
  bindLogin()
} else {
  bindDashboard().catch((error) => message('#admin-error', error.message || 'Không tải được trang quản trị.'))
}
