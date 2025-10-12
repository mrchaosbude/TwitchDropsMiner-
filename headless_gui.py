"""Headless GUI replacement for Twitch Drops Miner.

This module provides lightweight stand-ins for the Tk-based GUI classes so
that the original application can be driven from a command-line environment
without requiring a display server.  The stubs implement only the behaviour
that the rest of the codebase relies on and translate user interactions into
console prompts and log messages.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Dict, Optional, Set

from yarl import URL

logger = logging.getLogger("TwitchDrops")


@dataclass
class LoginData:
    """Simple container matching the GUI login data structure."""

    username: str
    password: str
    token: str


class _BaseComponent:
    def __init__(self, manager: "HeadlessGUI") -> None:
        self._manager = manager


class HeadlessStatus(_BaseComponent):
    def __init__(self, manager: "HeadlessGUI") -> None:
        super().__init__(manager)
        self._value: str = ""

    def update(self, message: str) -> None:
        self._value = message
        if message:
            logger.info("[status] %s", message)


class HeadlessTray(_BaseComponent):
    def change_icon(self, name: str) -> None:
        logger.debug("[tray] icon -> %s", name)

    def notify(self, body: str, title: str) -> None:
        logger.info("[tray] %s: %s", title, body.replace("\n", " "))

    def update_title(self, drop: Any | None) -> None:
        if drop is None:
            logger.debug("[tray] cleared title")
        else:
            try:
                rewards = drop.rewards_text()
            except AttributeError:
                rewards = str(drop)
            logger.info("[tray] watching drop: %s", rewards)

    def restore(self) -> None:
        logger.debug("[tray] restore requested")

    def minimize(self) -> None:
        logger.debug("[tray] minimize requested")

    def stop(self) -> None:
        logger.debug("[tray] stop requested")


class HeadlessWebsocketStatus(_BaseComponent):
    def __init__(self, manager: "HeadlessGUI") -> None:
        super().__init__(manager)
        self._entries: Dict[int, Dict[str, Any]] = {}

    def update(self, idx: int, *, status: Optional[str] = None, topics: Optional[int] = None) -> None:
        entry = self._entries.setdefault(idx, {"status": "", "topics": 0})
        if status is not None:
            entry["status"] = status
        if topics is not None:
            entry["topics"] = topics
        logger.debug("[websocket %s] status=%s topics=%s", idx, entry["status"], entry["topics"])

    def remove(self, idx: int) -> None:
        self._entries.pop(idx, None)
        logger.debug("[websocket %s] removed", idx)


class HeadlessProgress(_BaseComponent):
    def __init__(self, manager: "HeadlessGUI") -> None:
        super().__init__(manager)
        self._current_drop: Any | None = None

    def start_timer(self) -> None:
        # Timers are not displayed in headless mode.
        pass

    def stop_timer(self) -> None:
        pass

    def minute_almost_done(self) -> bool:
        return True

    def display(self, drop: Any | None, *, countdown: bool = True, subone: bool = False) -> None:
        self._current_drop = drop
        if drop is None:
            logger.info("[progress] cleared current drop")
        else:
            try:
                rewards = drop.rewards_text()
            except AttributeError:
                rewards = str(drop)
            logger.info("[progress] %s", rewards)


class HeadlessChannelList(_BaseComponent):
    def __init__(self, manager: "HeadlessGUI") -> None:
        super().__init__(manager)
        self._selection: Any | None = None

    def display(self, channel: Any, *, add: bool = False) -> None:
        logger.info("[channel] %s", getattr(channel, "name", channel))
        self._selection = channel

    def clear(self) -> None:
        self._selection = None
        logger.debug("[channel] cleared list")

    def get_selection(self) -> Any | None:
        return self._selection

    def set_watching(self, channel: Any) -> None:
        self._selection = channel
        logger.info("[channel] now watching %s", getattr(channel, "name", channel))

    def clear_watching(self) -> None:
        logger.debug("[channel] cleared watching state")

    def clear_selection(self) -> None:
        self._selection = None


class HeadlessInventory(_BaseComponent):
    def clear(self) -> None:
        logger.debug("[inventory] cleared")

    async def add_campaign(self, campaign: Any) -> None:
        logger.info("[inventory] campaign %s", getattr(campaign.game, "name", campaign))

    def update_drop(self, drop: Any) -> None:
        logger.debug("[inventory] updated drop %s", getattr(drop, "name", drop))


class HeadlessSettings(_BaseComponent):
    def __init__(self, manager: "HeadlessGUI") -> None:
        super().__init__(manager)
        self._games: Set[Any] = set()

    def set_games(self, games: Set[Any]) -> None:
        self._games = set(games)
        if games:
            logger.info("[settings] tracking games: %s", ", ".join(sorted(str(g) for g in games)))

    def clear_selection(self) -> None:
        pass


class HeadlessOutput(_BaseComponent):
    def print(self, message: str) -> None:
        logger.info("%s", message)


class HeadlessLoginForm(_BaseComponent):
    def __init__(self, manager: "HeadlessGUI") -> None:
        super().__init__(manager)
        self._status: str = ""
        self._user_id: int | None = None

    def update(self, status: str, user_id: int | None) -> None:
        self._status = status
        self._user_id = user_id
        logger.info("[login] %s (user: %s)", status, user_id if user_id is not None else "-")

    def clear(self, login: bool = False, password: bool = False, token: bool = False) -> None:
        # Nothing to clear in text UI.
        pass

    async def ask_login(self) -> LoginData:
        loop = asyncio.get_running_loop()

        def prompt() -> LoginData:
            username = input("Twitch username: ").strip()
            password = input("Twitch password: ")
            token = input("Two-factor token (optional): ").strip()
            return LoginData(username=username, password=password, token=token)

        return await loop.run_in_executor(None, prompt)

    async def ask_enter_code(self, page_url: URL, user_code: str) -> None:
        loop = asyncio.get_running_loop()

        def prompt() -> None:
            print("Open the following URL in a browser and enter the code shown below:")
            print(page_url)
            print(f"Device code: {user_code}")
            input("Press ENTER once authorization is complete...")

        await loop.run_in_executor(None, prompt)


class HeadlessGUI:
    def __init__(self, twitch: Any):
        self._twitch = twitch
        self.tray = HeadlessTray(self)
        self.status = HeadlessStatus(self)
        self.websockets = HeadlessWebsocketStatus(self)
        self.login = HeadlessLoginForm(self)
        self.progress = HeadlessProgress(self)
        self.channels = HeadlessChannelList(self)
        self.inv = HeadlessInventory(self)
        self.settings = HeadlessSettings(self)
        self.output = HeadlessOutput(self)
        self._close_requested: bool = False

    @property
    def close_requested(self) -> bool:
        return self._close_requested

    async def wait_until_closed(self) -> None:
        # Nothing to wait for in headless mode.
        return None

    async def coro_unless_closed(self, coro: Awaitable[Any]) -> Any:
        return await coro

    def prevent_close(self) -> None:
        self._close_requested = False

    def close(self, *args: Any, **kwargs: Any) -> int:
        self._close_requested = True
        self._twitch.close()
        return 0

    def start(self) -> None:
        logger.debug("[gui] start")

    def stop(self) -> None:
        logger.debug("[gui] stop")

    def close_window(self) -> None:
        logger.debug("[gui] close window")

    def grab_attention(self, *, sound: bool = True) -> None:
        logger.debug("[gui] attention requested")

    def set_games(self, games: Set[Any]) -> None:
        self.settings.set_games(games)

    def display_drop(self, drop: Any, *, countdown: bool = True, subone: bool = False) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)

    def clear_drop(self) -> None:
        self.progress.display(None)

    def print(self, message: str) -> None:
        self.output.print(message)

    def save(self, *, force: bool = False) -> None:
        logger.debug("[gui] save (force=%s)", force)
