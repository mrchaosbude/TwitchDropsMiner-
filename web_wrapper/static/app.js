const statusText = document.getElementById("status-text");
const trayTitle = document.getElementById("tray-title");
const loginStatus = document.getElementById("login-status");
const loginUser = document.getElementById("login-user");
const loginRequestBox = document.getElementById("login-request");
const loginMessage = document.getElementById("login-message");
const credentialsForm = document.getElementById("credentials-form");
const deviceForm = document.getElementById("device-form");
const deviceUrl = document.getElementById("device-url");
const deviceCode = document.getElementById("device-code");
const deviceConfirmButton = document.getElementById("device-confirm");
const channelList = document.getElementById("channel-list");
const currentChannel = document.getElementById("current-channel");
const currentDropBox = document.getElementById("current-drop");
const inventoryBox = document.getElementById("inventory");
const notificationsList = document.getElementById("notifications");
const logsBox = document.getElementById("logs");
const websocketsBox = document.getElementById("websockets");
const priorityModeLabel = document.getElementById("priority-mode-label");
const priorityModeValue = document.getElementById("priority-mode-value");
const priorityModeForm = document.getElementById("priority-mode-form");
const priorityModeSelect = document.getElementById("priority-mode-select");
const priorityListBox = document.getElementById("priority-list");
const excludeListBox = document.getElementById("exclude-list");
const priorityForm = document.getElementById("priority-form");
const priorityGameInput = document.getElementById("priority-game");
const priorityPositionInput = document.getElementById("priority-position");
const excludeForm = document.getElementById("exclude-form");
const excludeGameInput = document.getElementById("exclude-game");
const gameOptionsList = document.getElementById("games-options");
const refreshButton = document.getElementById("refresh-button");
const clearNotificationsButton = document.getElementById("clear-notifications");
const shutdownButton = document.getElementById("shutdown-button");
const toast = document.getElementById("toast");

let toastTimer = null;
let fetchingState = false;
let latestGames = [];

function showToast(message, type = "info") {
  toast.textContent = message;
  toast.classList.remove("hidden");
  toast.classList.add("show");
  toast.style.backgroundColor =
    type === "error" ? "rgba(248, 113, 113, 0.95)" : "rgba(30, 64, 175, 0.95)";
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  toastTimer = setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => {
      toast.classList.add("hidden");
    }, 300);
  }, 2500);
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      // Ignore JSON parsing failures.
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return null;
  }
  const contentType = response.headers.get("content-type");
  if (contentType && contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function resetForms() {
  credentialsForm.reset();
}

function createProgressBar(value) {
  const percentage = Math.max(0, Math.min(100, value * 100));
  const container = document.createElement("div");
  container.className = "progress-bar";
  const span = document.createElement("span");
  span.style.width = `${percentage}%`;
  container.appendChild(span);
  return container;
}

function renderSettingsList(container, items, emptyText, options = {}) {
  const { showIndex = false, onRemove = null } = options;
  if (!container) {
    return;
  }
  container.innerHTML = "";
  if (!Array.isArray(items) || !items.length) {
    const item = document.createElement("li");
    item.className = "empty-state";
    item.textContent = emptyText;
    container.appendChild(item);
    return;
  }

  const fragment = document.createDocumentFragment();
  items.forEach((value, index) => {
    const item = document.createElement("li");
    if (showIndex) {
      const badge = document.createElement("span");
      badge.className = "order-badge";
      badge.textContent = String(index + 1);
      item.appendChild(badge);
    }
    const label = document.createElement("span");
    label.textContent = String(value);
    item.appendChild(label);
    if (typeof onRemove === "function") {
      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "list-action";
      removeButton.textContent = "Remove";
      removeButton.addEventListener("click", () => {
        onRemove(value);
      });
      item.appendChild(removeButton);
    }
    fragment.appendChild(item);
  });
  container.appendChild(fragment);
}

function populateGameOptions(games) {
  if (!gameOptionsList) {
    return;
  }
  if (Array.isArray(games) && games.join("\u0000") === latestGames.join("\u0000")) {
    return;
  }
  latestGames = Array.isArray(games) ? [...games] : [];
  gameOptionsList.innerHTML = "";
  if (!Array.isArray(games) || !games.length) {
    return;
  }
  const seen = new Set();
  const fragment = document.createDocumentFragment();
  games.forEach((name) => {
    if (typeof name !== "string") {
      return;
    }
    const trimmed = name.trim();
    if (!trimmed || seen.has(trimmed)) {
      return;
    }
    seen.add(trimmed);
    const option = document.createElement("option");
    option.value = trimmed;
    fragment.appendChild(option);
  });
  gameOptionsList.appendChild(fragment);
}

async function handlePriorityRemoval(game) {
  if (!game) {
    return;
  }
  try {
    const response = await apiRequest("/settings/priority/remove", {
      method: "POST",
      body: JSON.stringify({ game }),
    });
    showToast(response?.message || `Removed ${game} from priority list`);
    await fetchState();
  } catch (error) {
    showToast(`Failed to remove ${game} from priority list: ${error.message}`, "error");
  }
}

async function handleExclusionRemoval(game) {
  if (!game) {
    return;
  }
  try {
    const response = await apiRequest("/settings/exclude/remove", {
      method: "POST",
      body: JSON.stringify({ game }),
    });
    showToast(response?.message || `Removed ${game} from exclusion list`);
    await fetchState();
  } catch (error) {
    showToast(`Failed to remove ${game} from exclusion list: ${error.message}`, "error");
  }
}

function renderSettings(settings) {
  if (priorityModeLabel) {
    const label = settings?.priority_mode_label || "Unknown priority mode";
    priorityModeLabel.textContent = label;
  }

  if (priorityModeValue) {
    const key = settings?.priority_mode || "";
    const value = settings?.priority_mode_value;
    if (key) {
      const parts = [`Mode key: ${key}`];
      if (Number.isFinite(value)) {
        parts.push(`Value: ${value}`);
      }
      priorityModeValue.textContent = parts.join(" · ");
    } else {
      priorityModeValue.textContent = "";
    }
  }

  if (priorityModeSelect) {
    const modes = Array.isArray(settings?.priority_modes)
      ? settings.priority_modes
      : [];
    const currentKey = settings?.priority_mode || "";
    priorityModeSelect.innerHTML = "";
    if (!modes.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No priority modes available";
      option.disabled = true;
      option.selected = true;
      priorityModeSelect.appendChild(option);
      priorityModeSelect.disabled = true;
    } else {
      priorityModeSelect.disabled = false;
      modes.forEach((mode) => {
        if (!mode || typeof mode.key !== "string") {
          return;
        }
        const option = document.createElement("option");
        option.value = mode.key;
        option.textContent = mode.label || mode.key;
        if (mode.selected || mode.key === currentKey) {
          option.selected = true;
        }
        priorityModeSelect.appendChild(option);
      });
      if (!priorityModeSelect.value && currentKey) {
        priorityModeSelect.value = currentKey;
      }
    }
    priorityModeSelect.dataset.current = currentKey;
  }

  renderSettingsList(
    priorityListBox,
    settings?.priority,
    "No games prioritized.",
    { showIndex: true, onRemove: handlePriorityRemoval }
  );
  renderSettingsList(excludeListBox, settings?.exclude, "No games excluded.", {
    onRemove: handleExclusionRemoval,
  });
}

function renderChannels(channels, watchingChannel, selectedChannel) {
  channelList.innerHTML = "";
  if (!channels?.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No channels available.";
    channelList.appendChild(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  channels.forEach((channel) => {
    const wrapper = document.createElement("div");
    wrapper.className = "channel";
    if (channel.id === watchingChannel) {
      wrapper.classList.add("watching");
    }
    if (channel.id === selectedChannel) {
      wrapper.classList.add("selected");
    }

    const title = document.createElement("h3");
    title.textContent = channel.name || channel.login;
    wrapper.appendChild(title);

    const subtitle = document.createElement("p");
    subtitle.textContent = `@${channel.login} · ${channel.status}`;
    wrapper.appendChild(subtitle);

    if (channel.game) {
      const game = document.createElement("p");
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = channel.game;
      game.appendChild(badge);
      wrapper.appendChild(game);
    }

    const viewers = document.createElement("p");
    if (typeof channel.viewers === "number") {
      viewers.textContent = `${channel.viewers} viewers`;
    } else {
      viewers.textContent = "Viewer count unknown";
    }
    wrapper.appendChild(viewers);

    const drops = document.createElement("p");
    drops.textContent = channel.drops_enabled ? "Drops enabled" : "Drops disabled";
    wrapper.appendChild(drops);

    const actions = document.createElement("div");
    actions.className = "channel-actions";
    const switchButton = document.createElement("button");
    switchButton.textContent = channel.id === watchingChannel ? "Watching" : "Switch to channel";
    switchButton.disabled = channel.id === watchingChannel;
    switchButton.addEventListener("click", async () => {
      try {
        await apiRequest("/channels/switch", {
          method: "POST",
          body: JSON.stringify({ channel_id: channel.id }),
        });
        showToast(`Switching to ${channel.name || channel.login}`);
        await fetchState();
      } catch (error) {
        showToast(`Failed to switch channel: ${error.message}`, "error");
      }
    });
    actions.appendChild(switchButton);
    wrapper.appendChild(actions);

    fragment.appendChild(wrapper);
  });

  channelList.appendChild(fragment);
}

function renderCurrentDrop(drop) {
  currentDropBox.innerHTML = "";
  if (!drop) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No drop in progress.";
    currentDropBox.appendChild(empty);
    return;
  }

  const dropProgress = Math.max(0, Math.min(1, drop.drop_progress ?? drop.progress ?? 0));

  const name = document.createElement("strong");
  name.textContent = drop.drop_name || drop.name || "Unknown drop";
  currentDropBox.appendChild(name);

  const rewards = document.createElement("p");
  rewards.textContent = drop.rewards || "Rewards unknown";
  currentDropBox.appendChild(rewards);

  currentDropBox.appendChild(createProgressBar(dropProgress));

  const percent = document.createElement("p");
  if (typeof drop.drop_percentage === "string" && drop.drop_percentage.trim()) {
    percent.textContent = drop.drop_percentage;
  } else {
    percent.textContent = `${Math.round(dropProgress * 100)}% complete`;
  }
  currentDropBox.appendChild(percent);

  const remainingValue = drop.drop_remaining_minutes ?? drop.remaining_minutes;
  const remaining = document.createElement("p");
  const remainingText =
    typeof remainingValue === "number" && Number.isFinite(remainingValue)
      ? remainingValue
      : "?";
  remaining.textContent = `Remaining minutes: ${remainingText}`;
  currentDropBox.appendChild(remaining);

  const campaignHeading = document.createElement("h4");
  campaignHeading.textContent = `Campaign: ${drop.campaign_name || drop.campaign_game || "Unknown"}`;
  currentDropBox.appendChild(campaignHeading);

  const campaignDetails = [];
  if (typeof drop.campaign_percentage === "string" && drop.campaign_percentage.trim()) {
    campaignDetails.push(drop.campaign_percentage);
  } else if (
    typeof drop.campaign_progress === "number" &&
    Number.isFinite(drop.campaign_progress)
  ) {
    campaignDetails.push(`${Math.round(drop.campaign_progress * 100)}% complete`);
  }

  if (
    typeof drop.campaign_claimed_drops === "number" &&
    typeof drop.campaign_total_drops === "number"
  ) {
    campaignDetails.push(
      `${drop.campaign_claimed_drops}/${drop.campaign_total_drops} drops`
    );
  }

  if (typeof drop.campaign_remaining_minutes === "number") {
    campaignDetails.push(`${drop.campaign_remaining_minutes} minutes remaining`);
  }

  if (campaignDetails.length) {
    const campaignMeta = document.createElement("p");
    campaignMeta.textContent = campaignDetails.join(" · ");
    currentDropBox.appendChild(campaignMeta);
  }
}

function renderInventory(campaigns) {
  inventoryBox.innerHTML = "";
  if (!campaigns?.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No campaign data available.";
    inventoryBox.appendChild(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  campaigns.forEach((campaign) => {
    const wrapper = document.createElement("div");
    wrapper.className = "campaign";

    const title = document.createElement("h3");
    title.textContent = `${campaign.name} · ${campaign.game}`;
    wrapper.appendChild(title);

    const status = document.createElement("p");
    status.textContent = `${campaign.status} · ${campaign.claimed_drops}/${campaign.total_drops} drops`;
    wrapper.appendChild(status);

    const metaFlags = [];
    if (typeof campaign.linked === "boolean") {
      metaFlags.push(campaign.linked ? "Account linked" : "Account not linked");
    }
    if (typeof campaign.eligible === "boolean") {
      metaFlags.push(campaign.eligible ? "Eligible" : "Not eligible");
    }
    if (metaFlags.length) {
      const metaLine = document.createElement("p");
      metaLine.className = "campaign-meta";
      metaLine.textContent = metaFlags.join(" · ");
      wrapper.appendChild(metaLine);
    }

    const required = Number(campaign.required_minutes || 0);
    const remaining = Number(campaign.remaining_minutes || 0);
    let progressValue = 0;
    if (required > 0) {
      progressValue = Math.min(1, Math.max(0, (required - remaining) / required));
    } else if (campaign.claimed_drops && campaign.total_drops) {
      progressValue = Math.min(1, campaign.claimed_drops / campaign.total_drops);
    }

    wrapper.appendChild(createProgressBar(progressValue));

    if (campaign.drops?.length) {
      const dropList = document.createElement("div");
      dropList.className = "drop-list";
      campaign.drops.forEach((drop) => {
        const dropEntry = document.createElement("div");
        dropEntry.className = "drop";

        const dropName = document.createElement("strong");
        dropName.textContent = drop.name;
        dropEntry.appendChild(dropName);

        const progress = Math.max(0, Math.min(1, drop.progress ?? 0));
        dropEntry.appendChild(createProgressBar(progress));

        const dropMeta = document.createElement("span");
        const rewardText = drop.rewards ? ` · ${drop.rewards}` : "";
        dropMeta.textContent = `${Math.round(progress * 100)}%${rewardText}`;
        dropEntry.appendChild(dropMeta);

        dropList.appendChild(dropEntry);
      });
      wrapper.appendChild(dropList);
    }

    fragment.appendChild(wrapper);
  });

  inventoryBox.appendChild(fragment);
}

function renderNotifications(notifications) {
  notificationsList.innerHTML = "";
  if (!notifications?.length) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.textContent = "No notifications.";
    notificationsList.appendChild(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  notifications.forEach((note) => {
    const item = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = new Date(note.timestamp).toLocaleString();
    item.appendChild(time);
    const title = document.createElement("strong");
    title.textContent = note.title;
    item.appendChild(title);
    const message = document.createElement("p");
    message.textContent = note.message;
    item.appendChild(message);
    fragment.appendChild(item);
  });
  notificationsList.appendChild(fragment);
}

function renderLogs(logs) {
  logsBox.textContent = logs?.length ? logs.join("\n") : "Waiting for log output…";
  logsBox.scrollTop = logsBox.scrollHeight;
}

function renderWebsockets(websockets) {
  websocketsBox.innerHTML = "";
  const entries = Object.entries(websockets || {});
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No websocket connections tracked.";
    websocketsBox.appendChild(empty);
    return;
  }
  const fragment = document.createDocumentFragment();
  entries.forEach(([key, ws]) => {
    const entry = document.createElement("div");
    entry.className = "socket-entry";
    const title = document.createElement("h4");
    title.textContent = `#${key}`;
    entry.appendChild(title);
    const status = document.createElement("p");
    status.textContent = `Status: ${ws.status}`;
    entry.appendChild(status);
    const topics = document.createElement("p");
    topics.textContent = `Topics: ${ws.topics}`;
    entry.appendChild(topics);
    fragment.appendChild(entry);
  });
  websocketsBox.appendChild(fragment);
}

function updateLoginUI(login) {
  const status = login?.status || "Unknown";
  loginStatus.textContent = `Status: ${status}`;
  loginUser.textContent = login?.user_id ? `User ID: ${login.user_id}` : "";

  const request = login?.request;
  const hasRequest = Boolean(request);
  loginRequestBox.classList.toggle("hidden", !hasRequest);
  if (!hasRequest) {
    credentialsForm.classList.add("hidden");
    deviceForm.classList.add("hidden");
    return;
  }

  loginMessage.textContent = request.message || "Action required";
  if (request.kind === "credentials") {
    credentialsForm.classList.remove("hidden");
    deviceForm.classList.add("hidden");
  } else if (request.kind === "device_code") {
    credentialsForm.classList.add("hidden");
    deviceForm.classList.remove("hidden");
    deviceUrl.textContent = request.data?.verification_uri || "";
    deviceUrl.href = request.data?.verification_uri || "#";
    deviceCode.textContent = request.data?.user_code || "";
  } else {
    credentialsForm.classList.add("hidden");
    deviceForm.classList.add("hidden");
  }
}

function updateUI(state) {
  statusText.textContent = state.status || "Idle";
  trayTitle.textContent = state.tray?.title
    ? `${state.tray.title}${state.attention_requests ? ` · Attention requests: ${state.attention_requests}` : ""}`
    : state.attention_requests
      ? `Attention requests: ${state.attention_requests}`
      : "";

  updateLoginUI(state.login);

  const watchingChannel = state.watching_channel;
  const selectedChannel = state.selected_channel;
  renderChannels(state.channels, watchingChannel, selectedChannel);

  if (watchingChannel) {
    const current = state.channels?.find((ch) => ch.id === watchingChannel);
    if (current) {
      currentChannel.textContent = `Watching ${current.name || current.login}`;
    } else {
      currentChannel.textContent = `Watching channel ${watchingChannel}`;
    }
  } else {
    currentChannel.textContent = "Not watching any channel.";
  }

  renderCurrentDrop(state.current_drop);
  populateGameOptions(state.games);
  renderSettings(state.settings);
  renderInventory(state.inventory);
  renderNotifications(state.notifications);
  renderLogs(state.logs);
  renderWebsockets(state.websockets);
}

async function fetchState() {
  if (fetchingState) {
    return;
  }
  fetchingState = true;
  try {
    const state = await apiRequest("/state");
    updateUI(state);
  } catch (error) {
    showToast(`Failed to load state: ${error.message}`, "error");
  } finally {
    fetchingState = false;
  }
}

credentialsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(credentialsForm);
  const payload = {
    username: formData.get("username"),
    password: formData.get("password"),
    token: formData.get("token") || "",
  };
  try {
    await apiRequest("/login/credentials", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showToast("Credentials submitted");
    resetForms();
    await fetchState();
  } catch (error) {
    showToast(`Login failed: ${error.message}`, "error");
  }
});

deviceConfirmButton.addEventListener("click", async () => {
  try {
    await apiRequest("/login/device", { method: "POST" });
    showToast("Device code confirmed");
    await fetchState();
  } catch (error) {
    showToast(`Failed to confirm device code: ${error.message}`, "error");
  }
});

if (priorityForm) {
  priorityForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!priorityGameInput) {
      return;
    }
    const game = priorityGameInput.value.trim();
    if (!game) {
      showToast("Enter a game name to prioritise.", "error");
      return;
    }
    const payload = { game };
    if (priorityPositionInput) {
      const rawPosition = priorityPositionInput.value.trim();
      if (rawPosition) {
        const parsed = Number.parseInt(rawPosition, 10);
        if (!Number.isFinite(parsed) || parsed < 1) {
          showToast("Position must be a positive number.", "error");
          return;
        }
        payload.position = parsed;
      }
    }
    try {
      const response = await apiRequest("/settings/priority/add", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      showToast(response?.message || `${game} added to priority list`);
      priorityGameInput.value = "";
      if (priorityPositionInput) {
        priorityPositionInput.value = "";
      }
      await fetchState();
    } catch (error) {
      showToast(`Failed to add ${game} to priority list: ${error.message}`, "error");
    }
  });
}

if (excludeForm) {
  excludeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!excludeGameInput) {
      return;
    }
    const game = excludeGameInput.value.trim();
    if (!game) {
      showToast("Enter a game name to exclude.", "error");
      return;
    }
    try {
      const response = await apiRequest("/settings/exclude/add", {
        method: "POST",
        body: JSON.stringify({ game }),
      });
      showToast(response?.message || `${game} added to exclusion list`);
      excludeGameInput.value = "";
      await fetchState();
    } catch (error) {
      showToast(`Failed to exclude ${game}: ${error.message}`, "error");
    }
  });
}

if (priorityModeForm) {
  priorityModeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!priorityModeSelect || priorityModeSelect.disabled) {
      return;
    }
    const mode = priorityModeSelect.value;
    const current = priorityModeSelect.dataset.current || "";
    if (!mode) {
      showToast("Select a priority mode to apply.", "error");
      return;
    }
    if (mode === current) {
      showToast("Priority mode already active.");
      return;
    }
    try {
      const response = await apiRequest("/settings/priority/mode", {
        method: "POST",
        body: JSON.stringify({ mode }),
      });
      showToast(response?.message || "Priority mode updated.");
      await fetchState();
    } catch (error) {
      showToast(`Failed to update priority mode: ${error.message}`, "error");
    }
  });
}

if (priorityModeSelect) {
  priorityModeSelect.addEventListener("change", () => {
    if (!priorityModeForm) {
      return;
    }
    priorityModeForm.requestSubmit();
  });
}

clearNotificationsButton.addEventListener("click", async () => {
  try {
    await apiRequest("/notifications/clear", { method: "POST" });
    showToast("Notifications cleared");
    await fetchState();
  } catch (error) {
    showToast(`Failed to clear notifications: ${error.message}`, "error");
  }
});

refreshButton.addEventListener("click", () => {
  fetchState();
});

shutdownButton.addEventListener("click", async () => {
  const confirmed = window.confirm("Are you sure you want to shut down the miner?");
  if (!confirmed) {
    return;
  }
  try {
    await apiRequest("/shutdown", { method: "POST" });
    showToast("Shutdown requested");
  } catch (error) {
    showToast(`Failed to request shutdown: ${error.message}`, "error");
  }
});

window.addEventListener("focus", () => {
  fetchState();
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    fetchState();
  }
});

setInterval(() => {
  fetchState();
}, 5000);

fetchState();
