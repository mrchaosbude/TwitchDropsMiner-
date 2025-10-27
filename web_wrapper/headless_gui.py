from __future__ import annotations

import asyncio
import os
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow imports from the main project when the adapter is executed directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if not os.environ.get("TWITCH_MINER_KEEP_ARGV"):
    sys.argv[0] = str(PROJECT_ROOT.joinpath("main.py"))

os.chdir(PROJECT_ROOT)

from constants import PriorityMode
from exceptions import ExitRequest
from inventory import DropsCampaign, TimedDrop
from translate import _
from utils import Game

if False:
    # typing imports for static analyzers; avoided at runtime
    from twitch import Twitch
    from channel import Channel


__all__ = [
    "GUIManager",
    "ChannelList",
    "WebsocketStatus",
    "LoginForm",
    "LoginData",
]


@dataclass
class Notification:
    title: str
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ChannelView:
    id: str
    login: str
    name: str
    status: str
    game: Optional[str]
    drops_enabled: bool
    viewers: Optional[int]
    acl_based: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "login": self.login,
            "name": self.name,
            "status": self.status,
            "game": self.game,
            "drops_enabled": self.drops_enabled,
            "viewers": self.viewers,
            "acl_based": self.acl_based,
        }


@dataclass
class DropView:
    id: str
    name: str
    remaining_minutes: int
    required_minutes: int
    progress: float
    claimed: bool
    can_earn: bool
    rewards: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "remaining_minutes": self.remaining_minutes,
            "required_minutes": self.required_minutes,
            "progress": self.progress,
            "claimed": self.claimed,
            "can_earn": self.can_earn,
            "rewards": self.rewards,
        }


@dataclass
class CampaignView:
    id: str
    name: str
    game: str
    status: str
    linked: bool
    eligible: bool
    required_minutes: int
    remaining_minutes: int
    claimed_drops: int
    total_drops: int
    drops: Dict[str, DropView] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "game": self.game,
            "status": self.status,
            "linked": self.linked,
            "eligible": self.eligible,
            "required_minutes": self.required_minutes,
            "remaining_minutes": self.remaining_minutes,
            "claimed_drops": self.claimed_drops,
            "total_drops": self.total_drops,
            "drops": [drop.as_dict() for drop in self.drops.values()],
        }


@dataclass
class DropProgressView:
    drop_id: str
    drop_name: str
    rewards: str
    drop_progress: float
    drop_percentage: str
    drop_remaining_minutes: int
    campaign_id: str
    campaign_name: str
    campaign_game: str
    campaign_progress: float
    campaign_percentage: str
    campaign_claimed_drops: int
    campaign_total_drops: int
    campaign_remaining_minutes: int
    seconds_remaining: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "drop_id": self.drop_id,
            "drop_name": self.drop_name,
            "rewards": self.rewards,
            "drop_progress": self.drop_progress,
            "drop_percentage": self.drop_percentage,
            "drop_remaining_minutes": self.drop_remaining_minutes,
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "campaign_game": self.campaign_game,
            "campaign_progress": self.campaign_progress,
            "campaign_percentage": self.campaign_percentage,
            "campaign_claimed_drops": self.campaign_claimed_drops,
            "campaign_total_drops": self.campaign_total_drops,
            "campaign_remaining_minutes": self.campaign_remaining_minutes,
            "seconds_remaining": self.seconds_remaining,
        }


@dataclass
class WebsocketView:
    status: str
    topics: int

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "topics": self.topics}


@dataclass
class LoginRequest:
    kind: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": self.message, "data": self.data}


@dataclass
class SettingsView:
    priority: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    priority_mode: str = ""
    priority_mode_value: int = 0
    priority_mode_label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "priority": list(self.priority),
            "exclude": list(self.exclude),
            "priority_mode": self.priority_mode,
            "priority_mode_value": self.priority_mode_value,
            "priority_mode_label": self.priority_mode_label,
        }


@dataclass
class HeadlessState:
    status_text: str = ""
    tray_icon: str = "pickaxe"
    tray_title: Optional[str] = None
    notifications: List[Notification] = field(default_factory=list)
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=500))
    channels: Dict[str, ChannelView] = field(default_factory=dict)
    watching_channel: Optional[str] = None
    selected_channel: Optional[str] = None
    current_drop: Optional[DropProgressView] = None
    websockets: Dict[int, WebsocketView] = field(default_factory=dict)
    inventory: Dict[str, CampaignView] = field(default_factory=dict)
    games: List[str] = field(default_factory=list)
    settings: SettingsView = field(default_factory=SettingsView)
    login_status: str = ""
    login_user_id: Optional[int] = None
    login_request: Optional[LoginRequest] = None
    attention_requests: int = 0
    closed: bool = False
    close_requested: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status_text,
            "tray": {"icon": self.tray_icon, "title": self.tray_title},
            "notifications": [note.as_dict() for note in self.notifications],
            "logs": list(self.logs),
            "channels": [channel.as_dict() for channel in self.channels.values()],
            "watching_channel": self.watching_channel,
            "selected_channel": self.selected_channel,
            "current_drop": self.current_drop.as_dict() if self.current_drop else None,
            "websockets": {
                str(idx): ws.as_dict() for idx, ws in sorted(self.websockets.items())
            },
            "inventory": [campaign.as_dict() for campaign in self.inventory.values()],
            "games": self.games,
            "settings": self.settings.as_dict(),
            "login": {
                "status": self.login_status,
                "user_id": self.login_user_id,
                "request": self.login_request.as_dict() if self.login_request else None,
            },
            "attention_requests": self.attention_requests,
            "closed": self.closed,
            "close_requested": self.close_requested,
        }


@dataclass
class LoginData:
    username: str
    password: str
    token: str


class ConsoleOutput:
    def __init__(self, manager: "GUIManager") -> None:
        self._manager = manager

    def print(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"[{timestamp}] {message}"
        self._manager.state.logs.append(line)


class StatusBar:
    def __init__(self, manager: "GUIManager") -> None:
        self._manager = manager

    def update(self, text: str) -> None:
        self._manager.state.status_text = text


class TrayIcon:
    def __init__(self, manager: "GUIManager") -> None:
        self._manager = manager

    def change_icon(self, icon: str) -> None:
        self._manager.state.tray_icon = icon

    def update_title(self, drop: Optional[TimedDrop]) -> None:
        if drop is None:
            self._manager.state.tray_title = None
        else:
            self._manager.state.tray_title = f"{drop.campaign.game.name}: {drop.name}"

    def notify(self, message: str, title: str) -> None:
        self._manager.state.notifications.append(Notification(title=title, message=message))

    def restore(self) -> None:
        self._manager.state.attention_requests += 1

    def stop(self) -> None:
        pass


class ChannelList:
    def __init__(self, manager: "GUIManager") -> None:
        self._manager = manager
        self._channels: Dict[str, "Channel"] = {}
        self._selection: Optional[str] = None
        self._watching: Optional[str] = None

    def clear(self) -> None:
        self._channels.clear()
        self._manager.state.channels.clear()
        self.clear_selection()
        self.clear_watching()

    def clear_selection(self) -> None:
        self._selection = None
        self._manager.state.selected_channel = None

    def display(self, channel: "Channel", *, add: bool = False) -> None:
        iid = channel.iid
        if not add and iid not in self._channels:
            return
        status: str
        if channel.online:
            status = _("gui", "channels", "online")
        elif channel.pending_online:
            status = _("gui", "channels", "pending")
        else:
            status = _("gui", "channels", "offline")
        view = ChannelView(
            id=iid,
            login=channel._login,
            name=channel.name,
            status=status,
            game=str(channel.game) if channel.game is not None else None,
            drops_enabled=channel.drops_enabled,
            viewers=channel.viewers,
            acl_based=channel.acl_based,
        )
        if add:
            self._channels[iid] = channel
        self._manager.state.channels[iid] = view

    def remove(self, channel: "Channel") -> None:
        iid = channel.iid
        self._channels.pop(iid, None)
        self._manager.state.channels.pop(iid, None)
        if self._selection == iid:
            self.clear_selection()
        if self._watching == iid:
            self.clear_watching()

    def set_watching(self, channel: "Channel") -> None:
        iid = channel.iid
        self._watching = iid
        self._manager.state.watching_channel = iid

    def clear_watching(self) -> None:
        self._watching = None
        self._manager.state.watching_channel = None

    def get_selection(self) -> Optional["Channel"]:
        if self._selection is None:
            return None
        return self._channels.get(self._selection)

    def select(self, channel_id: str) -> None:
        if channel_id not in self._channels:
            raise KeyError(channel_id)
        self._selection = channel_id
        self._manager.state.selected_channel = channel_id


class WebsocketStatus:
    def __init__(self, manager: "GUIManager") -> None:
        self._manager = manager

    def update(self, idx: int, *, status: Optional[str] = None, topics: Optional[int] = None) -> None:
        current = self._manager.state.websockets.get(idx)
        if current is None:
            current = WebsocketView(status=status or "", topics=topics or 0)
        else:
            if status is not None:
                current.status = status
            if topics is not None:
                current.topics = topics
        self._manager.state.websockets[idx] = current

    def remove(self, idx: int) -> None:
        self._manager.state.websockets.pop(idx, None)


class CampaignProgress:
    ALMOST_DONE_SECONDS = 10

    def __init__(self, manager: "GUIManager") -> None:
        self._manager = manager
        self._drop: Optional[TimedDrop] = None
        self._seconds: int = 0
        self._timer_task: Optional[asyncio.Task[None]] = None

    def stop_timer(self) -> None:
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

    def minute_almost_done(self) -> bool:
        return self._timer_task is None or self._seconds <= self.ALMOST_DONE_SECONDS

    def _update_time(self, seconds: Optional[int] = None) -> None:
        if seconds is not None:
            self._seconds = seconds
        if self._manager.state.current_drop is not None:
            view = self._manager.state.current_drop
            view.seconds_remaining = max(self._seconds, 0)

    async def _timer_loop(self) -> None:
        self._update_time(60)
        try:
            while self._seconds > 0:
                await asyncio.sleep(1)
                self._seconds -= 1
                self._update_time()
        finally:
            self._timer_task = None

    def start_timer(self) -> None:
        if self._timer_task is not None:
            return
        if self._drop is None or self._drop.remaining_minutes <= 0:
            self._update_time(60)
            return
        self._timer_task = asyncio.create_task(self._timer_loop())

    def display(self, drop: Optional[TimedDrop], *, countdown: bool = True, subone: bool = False) -> None:
        self._drop = drop
        self.stop_timer()
        if drop is None:
            self._manager.state.current_drop = None
            self._update_time(0)
            return
        campaign = drop.campaign
        drop_remaining = max(drop.remaining_minutes, 0)
        campaign_remaining = max(campaign.remaining_minutes, 0)
        view = DropProgressView(
            drop_id=drop.id,
            drop_name=drop.name,
            rewards=drop.rewards_text(),
            drop_progress=drop.progress,
            drop_percentage=f"{drop.progress:6.1%}",
            drop_remaining_minutes=drop_remaining,
            campaign_id=campaign.id,
            campaign_name=campaign.name,
            campaign_game=campaign.game.name,
            campaign_progress=campaign.progress,
            campaign_percentage=(
                f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
            ),
            campaign_claimed_drops=campaign.claimed_drops,
            campaign_total_drops=campaign.total_drops,
            campaign_remaining_minutes=campaign_remaining,
            seconds_remaining=60,
        )
        self._manager.state.current_drop = view
        if countdown:
            self.start_timer()
        elif subone:
            self._update_time(0)
        else:
            self._update_time(60)


class InventoryOverview:
    def __init__(self, manager: "GUIManager") -> None:
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
        view = CampaignView(
            id=campaign.id,
            name=campaign.name,
            game=campaign.game.name,
            status=status,
            linked=campaign.linked,
            eligible=campaign.eligible,
            required_minutes=campaign.required_minutes,
            remaining_minutes=campaign.remaining_minutes,
            claimed_drops=campaign.claimed_drops,
            total_drops=campaign.total_drops,
        )
        for drop in campaign.drops:
            view.drops[drop.id] = self._drop_view(drop)
        self._manager.state.inventory[campaign.id] = view

    def _drop_view(self, drop: TimedDrop) -> DropView:
        return DropView(
            id=drop.id,
            name=drop.name,
            remaining_minutes=max(drop.remaining_minutes, 0),
            required_minutes=drop.required_minutes,
            progress=drop.progress,
            claimed=drop.is_claimed,
            can_earn=drop.can_earn(),
            rewards=drop.rewards_text(),
        )

    def update_drop(self, drop: TimedDrop) -> None:
        campaign_id = drop.campaign.id
        if campaign_id not in self._manager.state.inventory:
            return
        campaign = self._manager.state.inventory[campaign_id]
        campaign.remaining_minutes = drop.campaign.remaining_minutes
        campaign.claimed_drops = drop.campaign.claimed_drops
        campaign.required_minutes = drop.campaign.required_minutes
        campaign.drops[drop.id] = self._drop_view(drop)


class SettingsPanel:
    def __init__(self, manager: "GUIManager") -> None:
        self._manager = manager
        self._settings = manager._twitch.settings
        self.refresh()

    def set_games(self, games: set[Game]) -> None:
        self._manager.state.games = sorted(game.name for game in games)
        self.refresh()

    def clear_selection(self) -> None:
        pass

    def refresh(self) -> None:
        state_settings = self._manager.state.settings

        priority = list(getattr(self._settings, "priority", []))
        state_settings.priority = priority

        exclude_values = getattr(self._settings, "exclude", set())
        state_settings.exclude = sorted(exclude_values)

        raw_mode = getattr(self._settings, "priority_mode", PriorityMode.PRIORITY_ONLY)
        if isinstance(raw_mode, PriorityMode):
            mode = raw_mode
        else:
            try:
                mode = PriorityMode(raw_mode)
            except Exception:
                mode = PriorityMode.PRIORITY_ONLY
                self._settings.priority_mode = mode

        state_settings.priority_mode = mode.name
        state_settings.priority_mode_value = int(mode.value)
        state_settings.priority_mode_label = self._priority_mode_label(mode)

    @staticmethod
    def _priority_mode_label(mode: PriorityMode) -> str:
        labels = {
            PriorityMode.PRIORITY_ONLY: _(
                "gui", "settings", "priority_modes", "priority_only"
            ),
            PriorityMode.ENDING_SOONEST: _(
                "gui", "settings", "priority_modes", "ending_soonest"
            ),
            PriorityMode.LOW_AVBL_FIRST: _(
                "gui", "settings", "priority_modes", "low_availability"
            ),
        }
        label = labels.get(mode)
        if label:
            return label
        return mode.name.replace("_", " ").title()


class Notebook:
    def __init__(self, manager: "GUIManager") -> None:
        self._manager = manager

    def add_tab(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_view_event(self, *args: Any, **kwargs: Any) -> None:
        pass

    def current_tab(self) -> int:
        return 0


class LoginForm:
    def __init__(self, manager: "GUIManager") -> None:
        self._manager = manager
        self._pending_credentials: Optional[asyncio.Future[LoginData]] = None
        self._pending_device_code: Optional[asyncio.Future[None]] = None

    def clear(self, login: bool = False, password: bool = False, token: bool = False) -> None:
        # Nothing to clear for headless implementation.
        pass

    async def ask_login(self) -> LoginData:
        self._manager.state.login_request = LoginRequest(
            kind="credentials",
            message=_("gui", "login", "request"),
        )
        loop = asyncio.get_running_loop()
        future: asyncio.Future[LoginData] = loop.create_future()
        self._pending_credentials = future
        try:
            return await self._manager.coro_unless_closed(future)
        finally:
            self._pending_credentials = None
            self._manager.state.login_request = None

    async def ask_enter_code(self, page_url, user_code: str) -> None:
        self._manager.state.login_request = LoginRequest(
            kind="device_code",
            message=_("gui", "login", "device_code").format(code=user_code),
            data={"verification_uri": str(page_url), "user_code": user_code},
        )
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        self._pending_device_code = future
        try:
            await self._manager.coro_unless_closed(future)
        finally:
            self._pending_device_code = None
            self._manager.state.login_request = None

    def submit_credentials(self, username: str, password: str, token: str = "") -> None:
        if self._pending_credentials is None or self._pending_credentials.done():
            raise RuntimeError("No login request is pending")
        self._pending_credentials.set_result(LoginData(username, password, token))

    def confirm_device_code(self) -> None:
        if self._pending_device_code is None or self._pending_device_code.done():
            raise RuntimeError("No device code confirmation requested")
        self._pending_device_code.set_result(None)

    def update(self, status: str, user_id: Optional[int]) -> None:
        self._manager.state.login_status = status
        self._manager.state.login_user_id = user_id

    @property
    def waiting_for_credentials(self) -> bool:
        return self._pending_credentials is not None and not self._pending_credentials.done()

    @property
    def waiting_for_device_code(self) -> bool:
        return self._pending_device_code is not None and not self._pending_device_code.done()


class GUIManager:
    def __init__(self, twitch: "Twitch") -> None:
        self._twitch = twitch
        self.state = HeadlessState()
        self._close_requested = asyncio.Event()
        self.output = ConsoleOutput(self)
        self.status = StatusBar(self)
        self.tray = TrayIcon(self)
        self.channels = ChannelList(self)
        self.websockets = WebsocketStatus(self)
        self.progress = CampaignProgress(self)
        self.inv = InventoryOverview(self)
        self.settings = SettingsPanel(self)
        self.login = LoginForm(self)
        self.tabs = Notebook(self)

    def prevent_close(self) -> None:
        self._close_requested.clear()
        self.state.close_requested = False

    def start(self) -> None:
        # Progress timer is driven automatically by display() calls.
        pass

    def stop(self) -> None:
        self.progress.stop_timer()

    def close(self, *args: Any) -> int:
        self._close_requested.set()
        self.state.close_requested = True
        self._twitch.close()
        return 0

    def close_window(self) -> None:
        self.state.closed = True

    def grab_attention(self, *, sound: bool = True) -> None:
        self.state.attention_requests += 1

    def save(self, *, force: bool = False) -> None:
        # No cached resources to save in headless mode.
        pass

    def set_games(self, games: set[Game]) -> None:
        self.settings.set_games(games)

    def display_drop(self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)
        self.tray.update_title(drop)

    def clear_drop(self) -> None:
        self.progress.display(None)
        self.tray.update_title(None)

    def print(self, message: str) -> None:
        self.output.print(message)

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    async def wait_until_closed(self) -> None:
        await self._close_requested.wait()

    async def coro_unless_closed(self, coro: Any) -> Any:
        tasks = [asyncio.ensure_future(coro), asyncio.ensure_future(self._close_requested.wait())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if self._close_requested.is_set():
            raise ExitRequest()
        return await next(iter(done))

    def stop_gui(self) -> None:
        self.progress.stop_timer()

    def tray_message(self, message: str, title: str) -> None:
        self.tray.notify(message, title)


