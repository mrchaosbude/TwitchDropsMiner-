"""Headless GUI adapter for TwitchDropsMiner.

This module replaces the original Tkinter-based GUI with a lightweight
in-memory implementation that keeps track of application state for the web
wrapper.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Deque, Dict, Iterable, Optional

from constants import MAX_WEBSOCKETS, WS_TOPICS_LIMIT, OUTPUT_FORMATTER
from exceptions import ExitRequest
from inventory import DropsCampaign, TimedDrop
from translate import _

if False:  # pragma: no cover - runtime duck typing only
    from twitch import Twitch
    from channel import Channel


logger = logging.getLogger("TwitchDrops")


def _utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone().isoformat()


@dataclass
class Notification:
    message: str
    title: Optional[str]
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ChannelState:
    id: int
    login: str
    name: str
    game: Optional[str] = None
    viewers: Optional[int] = None
    drops_enabled: bool = False
    status: str = "offline"
    acl_based: bool = False
    pending_online: bool = False


@dataclass
class DropState:
    id: str
    name: str
    campaign: str
    game: str
    required_minutes: int
    current_minutes: int
    remaining_minutes: int
    progress: float
    ends_at: str | None
    rewards: list[str]


@dataclass
class CampaignState:
    id: str
    name: str
    game: str
    status: str
    eligible: bool
    linked: bool
    progress: float
    claimed_drops: int
    total_drops: int
    starts_at: str | None
    ends_at: str | None


@dataclass
class HeadlessState:
    status_text: str = ""
    tray_icon: str = "pickaxe"
    tray_title: Optional[str] = None
    games: list[str] = field(default_factory=list)
    drop: Optional[DropState] = None
    channels: Dict[int, ChannelState] = field(default_factory=dict)
    watching_channel: Optional[int] = None
    selected_channel: Optional[int] = None
    inventory: Dict[str, CampaignState] = field(default_factory=dict)
    notifications: list[Notification] = field(default_factory=list)
    logs: Deque[str] = field(default_factory=lambda: deque(maxlen=500))
    login_status: str = _("gui", "login", "logged_out")
    login_user_id: Optional[int] = None
    login_prompt: Optional[str] = None
    login_device_code: Optional[str] = None
    login_verification_uri: Optional[str] = None
    websockets: Dict[int, dict[str, Any]] = field(default_factory=dict)
    attention_requested: bool = False
    running: bool = False
    close_requested: bool = False
    last_error: Optional[str] = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "status_text": self.status_text,
            "tray_icon": self.tray_icon,
            "tray_title": self.tray_title,
            "games": list(self.games),
            "drop": None if self.drop is None else self.drop.__dict__,
            "channels": {cid: cs.__dict__ for cid, cs in self.channels.items()},
            "watching_channel": self.watching_channel,
            "selected_channel": self.selected_channel,
            "inventory": {cid: cs.__dict__ for cid, cs in self.inventory.items()},
            "notifications": [
                {"message": n.message, "title": n.title, "created_at": n.created_at.isoformat()}
                for n in self.notifications
            ],
            "logs": list(self.logs),
            "login_status": self.login_status,
            "login_user_id": self.login_user_id,
            "login_prompt": self.login_prompt,
            "login_device_code": self.login_device_code,
            "login_verification_uri": self.login_verification_uri,
            "websockets": self.websockets,
            "attention_requested": self.attention_requested,
            "running": self.running,
            "close_requested": self.close_requested,
            "last_error": self.last_error,
        }


class HeadlessTray:
    def __init__(self, manager: "GUIManager"):
        self._manager = manager

    def change_icon(self, icon: str) -> None:
        self._manager.state.tray_icon = icon

    def update_title(self, drop: TimedDrop | None) -> None:
        if drop is None:
            self._manager.state.tray_title = None
        else:
            self._manager.state.tray_title = f"{drop.campaign.game.name}: {drop.name}"

    def stop(self) -> None:
        return

    def notify(self, message: str, title: str | None = None, duration: float = 10) -> None:
        self._manager.state.notifications.append(Notification(message=message, title=title))


class HeadlessStatus:
    def __init__(self, manager: "GUIManager"):
        self._manager = manager

    def update(self, status: str) -> None:
        self._manager.state.status_text = status


class HeadlessWebsocketStatus:
    def __init__(self, manager: "GUIManager"):
        self._manager = manager
        self._manager.state.websockets = {
            idx: {"status": _("gui", "websocket", "disconnected"), "topics": 0}
            for idx in range(MAX_WEBSOCKETS)
        }

    def update(self, idx: int, status: str | None = None, topics: int | None = None) -> None:
        entry = self._manager.state.websockets.setdefault(
            idx, {"status": _("gui", "websocket", "disconnected"), "topics": 0}
        )
        if status is not None:
            entry["status"] = status
        if topics is not None:
            entry["topics"] = topics
        entry["limit"] = WS_TOPICS_LIMIT

    def remove(self, idx: int) -> None:
        self._manager.state.websockets.pop(idx, None)


class HeadlessChannels:
    def __init__(self, manager: "GUIManager"):
        self._manager = manager
        self._channels: Dict[str, "Channel"] = {}
        self._selected: Optional[int] = None

    def clear(self) -> None:
        self._channels.clear()
        self._manager.state.channels.clear()
        self._manager.state.selected_channel = None

    def display(self, channel: "Channel", *, add: bool = False) -> None:
        if not add and str(channel.id) not in self._channels:
            return
        self._channels[str(channel.id)] = channel
        status: str
        if channel.online:
            status = _("gui", "channels", "online")
        elif channel.pending_online:
            status = _("gui", "channels", "pending")
        else:
            status = _("gui", "channels", "offline")
        self._manager.state.channels[channel.id] = ChannelState(
            id=channel.id,
            login=channel._login,
            name=channel.name,
            game=str(channel.game or ""),
            viewers=channel.viewers,
            drops_enabled=channel.drops_enabled,
            status=status,
            acl_based=channel.acl_based,
            pending_online=channel.pending_online,
        )

    def remove(self, channel: "Channel") -> None:
        self._channels.pop(str(channel.id), None)
        self._manager.state.channels.pop(channel.id, None)
        if self._selected == channel.id:
            self._selected = None
            self._manager.state.selected_channel = None

    def clear_watching(self) -> None:
        self._manager.state.watching_channel = None

    def set_watching(self, channel: "Channel") -> None:
        self._manager.state.watching_channel = channel.id

    def get_selection(self) -> "Channel" | None:
        if self._selected is None:
            return None
        return self._channels.get(str(self._selected))

    def clear_selection(self) -> None:
        self._selected = None
        self._manager.state.selected_channel = None

    def set_selection(self, channel_id: Optional[int]) -> None:
        self._selected = channel_id
        self._manager.state.selected_channel = channel_id


class HeadlessProgress:
    ALMOST_DONE_SECONDS = 10

    def __init__(self, manager: "GUIManager"):
        self._manager = manager
        self._drop: TimedDrop | None = None
        self._seconds: int = 0
        self._timer_task: asyncio.Task[None] | None = None

    def _stop_timer(self) -> None:
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

    async def _timer(self) -> None:
        try:
            while self._seconds > 0:
                await asyncio.sleep(1)
                self._seconds -= 1
                state = self._manager.state.drop
                if state is not None:
                    state.remaining_minutes = max(state.remaining_minutes - (1 / 60), 0)
        except asyncio.CancelledError:
            pass
        finally:
            self._timer_task = None

    def stop_timer(self) -> None:
        self._stop_timer()

    def minute_almost_done(self) -> bool:
        return self._timer_task is None or self._seconds <= self.ALMOST_DONE_SECONDS

    def display(self, drop: TimedDrop | None, *, countdown: bool = True, subone: bool = False) -> None:
        self._drop = drop
        self._stop_timer()
        if drop is None:
            self._manager.state.drop = None
            self._seconds = 0
            return
        rewards = [benefit.name for benefit in drop.benefits]
        self._manager.state.drop = DropState(
            id=drop.id,
            name=drop.name,
            campaign=drop.campaign.name,
            game=drop.campaign.game.name,
            required_minutes=drop.required_minutes,
            current_minutes=drop.current_minutes,
            remaining_minutes=drop.remaining_minutes,
            progress=drop.progress,
            ends_at=_utc_iso(drop.ends_at),
            rewards=rewards,
        )
        if countdown:
            self._seconds = 60
            loop = asyncio.get_running_loop()
            self._timer_task = loop.create_task(self._timer())
        elif subone:
            self._seconds = 0
        else:
            self._seconds = 60


class HeadlessInventory:
    def __init__(self, manager: "GUIManager"):
        self._manager = manager

    def clear(self) -> None:
        self._manager.state.inventory.clear()

    async def add_campaign(self, campaign: DropsCampaign) -> None:
        status: str
        if campaign.active:
            status = _("gui", "inventory", "status", "active")
        elif campaign.upcoming:
            status = _("gui", "inventory", "status", "upcoming")
        else:
            status = _("gui", "inventory", "status", "expired")
        self._manager.state.inventory[campaign.id] = CampaignState(
            id=campaign.id,
            name=campaign.name,
            game=campaign.game.name,
            status=status,
            eligible=campaign.eligible,
            linked=campaign.linked,
            progress=campaign.progress,
            claimed_drops=campaign.claimed_drops,
            total_drops=campaign.total_drops,
            starts_at=_utc_iso(campaign.starts_at),
            ends_at=_utc_iso(campaign.ends_at),
        )

    def update_drop(self, drop: TimedDrop) -> None:
        if drop.campaign.id not in self._manager.state.inventory:
            return
        campaign_state = self._manager.state.inventory[drop.campaign.id]
        campaign_state.progress = drop.campaign.progress
        campaign_state.claimed_drops = drop.campaign.claimed_drops
        campaign_state.total_drops = drop.campaign.total_drops
        if drop.campaign.active:
            campaign_state.status = _("gui", "inventory", "status", "active")
        elif drop.campaign.upcoming:
            campaign_state.status = _("gui", "inventory", "status", "upcoming")
        else:
            campaign_state.status = _("gui", "inventory", "status", "expired")
        if self._manager.state.drop and self._manager.state.drop.id == drop.id:
            self._manager.state.drop.progress = drop.progress
            self._manager.state.drop.current_minutes = drop.current_minutes
            self._manager.state.drop.remaining_minutes = drop.remaining_minutes


@dataclass
class LoginData:
    username: str
    password: str
    token: str


class HeadlessLoginForm:
    def __init__(self, manager: "GUIManager"):
        self._manager = manager
        self._credentials_event = asyncio.Event()
        self._credentials: Optional[LoginData] = None

    def clear(self, login: bool = False, password: bool = False, token: bool = False) -> None:
        if self._credentials is None:
            return
        username = "" if login else self._credentials.username
        password_value = "" if password else self._credentials.password
        token_value = "" if token else self._credentials.token
        self._credentials = LoginData(username, password_value, token_value)

    def submit_credentials(self, username: str, password: str, token: str = "") -> None:
        self._credentials = LoginData(username=username.strip(), password=password, token=token.strip())
        self._credentials_event.set()

    async def ask_login(self) -> LoginData:
        self._manager.state.login_prompt = "login"
        self._manager.state.attention_requested = True
        self._credentials_event.clear()
        await self._manager.coro_unless_closed(self._credentials_event.wait())
        self._manager.state.attention_requested = False
        data = self._credentials
        if data is None:
            raise ExitRequest()
        return data

    async def ask_enter_code(self, page_url, user_code: str) -> None:
        self._manager.state.login_prompt = "device"
        self._manager.state.login_device_code = user_code
        self._manager.state.login_verification_uri = str(page_url)
        self._manager.print(_("gui", "login", "request"))
        self._manager.print(
            f"Enter this code on Twitch's device activation page: {user_code}"
        )

    def update(self, status: str, user_id: int | None) -> None:
        self._manager.state.login_status = status
        self._manager.state.login_user_id = user_id
        if status == _("gui", "login", "logged_in"):
            self._manager.state.login_prompt = None
            self._manager.state.login_device_code = None
            self._manager.state.login_verification_uri = None


class HeadlessLogger(logging.Handler):
    def __init__(self, manager: "GUIManager"):
        super().__init__()
        self._manager = manager

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # pragma: no cover - defensive, same as logging.Handler
            return
        self._manager.print(message)


class GUIManager:
    def __init__(self, twitch: "Twitch"):
        self._twitch = twitch
        self.state = HeadlessState()
        self.state.running = False
        self._close_event = asyncio.Event()
        self._close_event.clear()
        self._poll_task: asyncio.Task[None] | None = None
        self.tray = HeadlessTray(self)
        self.status = HeadlessStatus(self)
        self.websockets = HeadlessWebsocketStatus(self)
        self.login = HeadlessLoginForm(self)
        self.progress = HeadlessProgress(self)
        self.channels = HeadlessChannels(self)
        self.inv = HeadlessInventory(self)
        self._logs = self.state.logs
        self._handler = HeadlessLogger(self)
        self._handler.setFormatter(OUTPUT_FORMATTER)
        logging.getLogger("TwitchDrops").addHandler(self._handler)

    def prevent_close(self) -> None:
        self._close_event.clear()
        self.state.close_requested = False

    def start(self) -> None:
        self.state.running = True

    def stop(self) -> None:
        self.progress.stop_timer()
        self.state.running = False

    def close(self, *args: Any) -> int:
        self.state.close_requested = True
        self._close_event.set()
        self._twitch.close()
        return 0

    def close_window(self) -> None:
        logging.getLogger("TwitchDrops").removeHandler(self._handler)
        self.state.running = False

    def grab_attention(self, *, sound: bool = True) -> None:
        self.state.attention_requested = True

    def set_games(self, games: Iterable[Any]) -> None:
        self.state.games = [str(game) for game in games]

    def clear_drop(self) -> None:
        self.progress.display(None)

    def display_drop(self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)
        self.tray.update_title(drop)

    def save(self, *, force: bool = False) -> None:
        return

    def print(self, message: str) -> None:
        text = message.rstrip()
        if not text:
            return
        for line in text.splitlines():
            self._logs.append(line)

    def tray_notify(self, message: str, title: str | None = None) -> None:
        self.tray.notify(message, title)

    @property
    def close_requested(self) -> bool:
        return self._close_event.is_set()

    async def wait_until_closed(self) -> None:
        await self._close_event.wait()

    async def coro_unless_closed(self, coro: Awaitable[Any]) -> Any:
        done, pending = await asyncio.wait(
            {asyncio.create_task(coro), asyncio.create_task(self._close_event.wait())},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if self._close_event.is_set():
            raise ExitRequest()
        return await next(iter(done))

    def stop_polling(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    def set_last_error(self, message: str | None) -> None:
        self.state.last_error = message

    def select_channel(self, channel_id: Optional[int]) -> None:
        self.channels.set_selection(channel_id)

    def notify_error(self, message: str) -> None:
        self.state.last_error = message
        self.print(message)


__all__ = [
    "GUIManager",
    "HeadlessState",
    "LoginData",
]
