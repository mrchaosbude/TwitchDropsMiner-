const REFRESH_INTERVAL = 4000;
let pollTimer = null;
let lastErrorMessage = null;

const elements = {
  statusText: document.getElementById('status-text'),
  runningIndicator: document.getElementById('running-indicator'),
  watching: document.getElementById('watching-channel'),
  selected: document.getElementById('selected-channel'),
  dropInfo: document.getElementById('drop-info'),
  channelsBody: document.getElementById('channels-body'),
  inventoryBody: document.getElementById('inventory-body'),
  websocketList: document.getElementById('websocket-list'),
  notificationsList: document.getElementById('notifications-list'),
  logOutput: document.getElementById('log-output'),
  loginStatus: document.getElementById('login-status'),
  deviceLogin: document.getElementById('device-login'),
  deviceCode: document.getElementById('device-code'),
  verificationLink: document.getElementById('verification-link'),
  loginForm: document.getElementById('login-form'),
  settingsForm: document.getElementById('settings-form'),
  settingsFeedback: document.getElementById('settings-feedback'),
  startBtn: document.getElementById('start-btn'),
  stopBtn: document.getElementById('stop-btn'),
  toast: document.getElementById('toast'),
  lastError: document.getElementById('last-error'),
};

function showToast(message, { error = false, duration = 3500 } = {}) {
  if (!elements.toast) return;
  elements.toast.textContent = message;
  elements.toast.classList.remove('hidden', 'error', 'visible');
  if (error) {
    elements.toast.classList.add('error');
  }
  requestAnimationFrame(() => {
    elements.toast.classList.add('visible');
  });
  setTimeout(() => {
    elements.toast.classList.remove('visible');
  }, duration);
}

async function callAPI(path, { method = 'GET', body } = {}) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = 'Request failed';
    try {
      const payload = await response.json();
      detail = payload.detail || JSON.stringify(payload);
    } catch (err) {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return null;
  }
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }
  return null;
}

function formatPercent(value) {
  if (typeof value !== 'number' || !isFinite(value)) {
    return '0%';
  }
  return `${Math.round(value * 100)}%`;
}

function formatMinutes(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'N/A';
  }
  const minutes = Math.max(0, Number(value));
  if (minutes >= 120) {
    return `${(minutes / 60).toFixed(1)} hrs`;
  }
  return `${minutes.toFixed(1)} mins`;
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString();
}

function parseList(value) {
  if (!value) return [];
  return value
    .split(/[,\n]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

async function handleStart() {
  try {
    elements.startBtn.disabled = true;
    await callAPI('/start', { method: 'POST' });
    showToast('Miner starting…');
  } catch (error) {
    showToast(error.message, { error: true });
  } finally {
    setTimeout(() => {
      elements.startBtn.disabled = false;
    }, 500);
  }
}

async function handleStop() {
  try {
    elements.stopBtn.disabled = true;
    await callAPI('/stop', { method: 'POST' });
    showToast('Miner stopping…');
  } catch (error) {
    showToast(error.message, { error: true });
  } finally {
    setTimeout(() => {
      elements.stopBtn.disabled = false;
    }, 500);
  }
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  const formData = new FormData(elements.loginForm);
  const payload = {
    username: formData.get('username'),
    password: formData.get('password'),
    token: formData.get('token') || '',
  };
  try {
    await callAPI('/login', { method: 'POST', body: payload });
    showToast('Login submitted');
    elements.loginForm.reset();
  } catch (error) {
    showToast(error.message, { error: true });
  }
}

async function handleSettingsSubmit(event) {
  event.preventDefault();
  const formData = new FormData(elements.settingsForm);
  const payload = {};
  const language = formData.get('language');
  if (language) payload.language = language;
  payload.dark_mode = formData.get('dark_mode') === 'on';
  const excludeRaw = (formData.get('exclude') || '').trim();
  payload.exclude = excludeRaw ? parseList(excludeRaw) : [];
  const priorityRaw = (formData.get('priority') || '').trim();
  payload.priority = priorityRaw ? parseList(priorityRaw) : [];
  const connectionQuality = formData.get('connection_quality');
  if (connectionQuality) {
    payload.connection_quality = Number(connectionQuality);
  }
  payload.tray_notifications = formData.get('tray_notifications') === 'on';
  const priorityMode = formData.get('priority_mode');
  if (priorityMode) {
    payload.priority_mode = priorityMode;
  }

  try {
    const updated = await callAPI('/settings', { method: 'PATCH', body: payload });
    applySettings(updated);
    elements.settingsFeedback.textContent = 'Settings saved.';
    showToast('Settings updated');
  } catch (error) {
    elements.settingsFeedback.textContent = error.message;
    showToast(error.message, { error: true });
  }
}

async function handleChannelSelect(event) {
  const row = event.currentTarget;
  const channelId = Number(row.dataset.channelId);
  if (!Number.isFinite(channelId)) return;
  try {
    await callAPI('/select-channel', {
      method: 'POST',
      body: { channel_id: channelId },
    });
    showToast(`Channel #${channelId} selected`);
  } catch (error) {
    showToast(error.message, { error: true });
  }
}

function applySettings(settings) {
  if (!settings) return;
  elements.settingsForm.language.value = settings.language || '';
  elements.settingsForm.dark_mode.checked = Boolean(settings.dark_mode);
  elements.settingsForm.exclude.value = (settings.exclude || []).join('\n');
  elements.settingsForm.priority.value = (settings.priority || []).join('\n');
  elements.settingsForm.connection_quality.value = settings.connection_quality || '';
  elements.settingsForm.tray_notifications.checked = Boolean(settings.tray_notifications);
  elements.settingsForm.priority_mode.value = settings.priority_mode || '';
}

async function loadSettings() {
  try {
    const data = await callAPI('/settings');
    applySettings(data);
  } catch (error) {
    elements.settingsFeedback.textContent = error.message;
  }
}

let loadingState = false;

async function fetchState() {
  if (loadingState) return;
  loadingState = true;
  try {
    const state = await callAPI('/state');
    updateState(state);
  } catch (error) {
    showToast(`State update failed: ${error.message}`, { error: true, duration: 5000 });
  } finally {
    loadingState = false;
  }
}

function updateState(state) {
  if (!state) return;

  const running = Boolean(state.running);
  elements.runningIndicator.textContent = running ? 'Running' : 'Stopped';
  elements.runningIndicator.classList.toggle('running', running);
  elements.startBtn.disabled = running;
  elements.stopBtn.disabled = !running;

  elements.statusText.textContent = state.status_text || 'Idle';

  const channels = Object.values(state.channels || {}).map((channel) => ({
    ...channel,
    id: Number(channel.id),
  }));
  const channelById = new Map(channels.map((c) => [c.id, c]));

  const watching = state.watching_channel;
  const selected = state.selected_channel;

  elements.watching.textContent =
    channelById.get(watching)?.name || (watching ? `#${watching}` : '—');
  elements.selected.textContent =
    channelById.get(selected)?.name || (selected ? `#${selected}` : '—');

  renderChannels(channels, { watching, selected });
  renderDrop(state.drop);
  renderInventory(Object.values(state.inventory || {}));
  renderWebsockets(state.websockets || {});
  renderNotifications(state.notifications || []);
  renderLogs(state.logs || []);
  renderLogin(state);
  renderError(state.last_error);
}

function renderError(message) {
  if (!elements.lastError) return;
  if (message) {
    if (message !== lastErrorMessage) {
      showToast(message, { error: true, duration: 6000 });
      lastErrorMessage = message;
    }
    elements.lastError.textContent = message;
    elements.lastError.classList.remove('hidden');
  } else {
    elements.lastError.classList.add('hidden');
    elements.lastError.textContent = '';
    lastErrorMessage = null;
  }
}

function renderLogin(state) {
  const status = state.login_status || 'Unknown';
  const userId = state.login_user_id;
  const prompt = state.login_prompt;
  elements.loginStatus.textContent = userId
    ? `${status} (user #${userId})`
    : status;

  if (prompt === 'device') {
    elements.deviceLogin.classList.remove('hidden');
    elements.deviceCode.textContent = state.login_device_code || '—';
    if (state.login_verification_uri) {
      elements.verificationLink.href = state.login_verification_uri;
      elements.verificationLink.textContent = state.login_verification_uri;
    }
  } else {
    elements.deviceLogin.classList.add('hidden');
  }
}

function renderDrop(drop) {
  if (!drop) {
    elements.dropInfo.innerHTML = '<p class="empty">No active drop.</p>';
    return;
  }

  const percent = formatPercent(drop.progress);
  const rewards = (drop.rewards || []).join(', ');
  elements.dropInfo.innerHTML = `
    <div>
      <h3>${drop.name}</h3>
      <p class="muted">${drop.game} · ${drop.campaign}</p>
    </div>
    <div class="progress">
      <div class="progress-track">
        <div class="progress-value" style="width: ${percent}"></div>
      </div>
      <div class="progress-labels">
        <span>${percent}</span>
        <span>Remaining: ${formatMinutes(drop.remaining_minutes)}</span>
      </div>
    </div>
    <p class="muted">Rewards: ${rewards || '—'}</p>
    <p class="muted">Ends: ${formatDate(drop.ends_at)}</p>
  `;
}

function renderChannels(channels, { watching, selected }) {
  const tbody = elements.channelsBody;
  tbody.innerHTML = '';
  if (!channels.length) {
    tbody.innerHTML = '<tr class="empty"><td colspan="5">No channels available.</td></tr>';
    return;
  }
  const sorted = channels.slice().sort((a, b) => a.name.localeCompare(b.name));
  for (const channel of sorted) {
    const row = document.createElement('tr');
    row.dataset.channelId = channel.id;
    if (channel.id === watching) row.classList.add('watching');
    if (channel.id === selected) row.classList.add('selected');
    row.innerHTML = `
      <td>
        <div class="channel-name">${channel.name}</div>
        <div class="muted">${channel.login}</div>
      </td>
      <td>${channel.game || '—'}</td>
      <td>${channel.status || '—'}</td>
      <td>${channel.drops_enabled ? 'Enabled' : 'Disabled'}</td>
      <td>${channel.viewers ?? '—'}</td>
    `;
    row.addEventListener('click', handleChannelSelect);
    tbody.appendChild(row);
  }
}

function renderInventory(entries) {
  const tbody = elements.inventoryBody;
  tbody.innerHTML = '';
  if (!entries.length) {
    tbody.innerHTML = '<tr class="empty"><td colspan="6">No campaigns loaded yet.</td></tr>';
    return;
  }
  const sorted = entries
    .map((entry) => ({
      ...entry,
      ends_at: entry.ends_at,
    }))
    .sort((a, b) => (a.ends_at || '').localeCompare(b.ends_at || ''));

  for (const entry of sorted) {
    const claimed = `${entry.claimed_drops ?? 0}/${entry.total_drops ?? 0}`;
    const percent = formatPercent(entry.progress ?? 0);
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${entry.name}</td>
      <td>${entry.game}</td>
      <td>${entry.status}</td>
      <td>${percent}</td>
      <td>${claimed}</td>
      <td>${formatDate(entry.ends_at)}</td>
    `;
    tbody.appendChild(row);
  }
}

function renderWebsockets(websockets) {
  const list = elements.websocketList;
  list.innerHTML = '';
  const entries = Object.entries(websockets);
  if (!entries.length) {
    list.innerHTML = '<li class="muted">No websocket data.</li>';
    return;
  }
  for (const [idx, info] of entries) {
    const li = document.createElement('li');
    const status = (info.status || '').toLowerCase();
    if (status.includes('connected')) {
      li.classList.add('good');
    } else if (status.includes('pending') || status.includes('connecting')) {
      li.classList.add('warn');
    }
    const topics = `${info.topics ?? 0}/${info.limit ?? '?'}`;
    li.textContent = `Socket #${Number(idx) + 1}: ${info.status} (${topics} topics)`;
    list.appendChild(li);
  }
}

function renderNotifications(notifications) {
  const list = elements.notificationsList;
  list.innerHTML = '';
  if (!notifications.length) {
    list.innerHTML = '<li class="muted">No notifications yet.</li>';
    return;
  }
  for (const note of notifications.slice(-6).reverse()) {
    const li = document.createElement('li');
    if (note.title) {
      const strong = document.createElement('strong');
      strong.textContent = note.title;
      li.appendChild(strong);
    }
    const message = document.createElement('span');
    message.textContent = note.message;
    li.appendChild(message);
    if (note.created_at) {
      const time = document.createElement('div');
      time.classList.add('muted');
      time.textContent = formatDate(note.created_at);
      li.appendChild(time);
    }
    list.appendChild(li);
  }
}

function renderLogs(logs) {
  if (!Array.isArray(logs)) return;
  const lines = logs.slice(-400);
  elements.logOutput.textContent = lines.join('\n');
  elements.logOutput.scrollTop = elements.logOutput.scrollHeight;
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  fetchState();
  pollTimer = setInterval(fetchState, REFRESH_INTERVAL);
}

function init() {
  elements.startBtn.addEventListener('click', handleStart);
  elements.stopBtn.addEventListener('click', handleStop);
  elements.loginForm.addEventListener('submit', handleLoginSubmit);
  elements.settingsForm.addEventListener('submit', handleSettingsSubmit);
  loadSettings();
  startPolling();
}

init();
