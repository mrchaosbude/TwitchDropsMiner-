from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from getpass import getpass
from time import monotonic
from typing import Any, Iterable

from utils import Game, webopen


logger = logging.getLogger("TwitchDrops")


@dataclass
class LoginData:
    """Container holding login information entered by the user."""

    username: str
    password: str
    token: str


class ConsoleOutput:
    """Simple console logger used by the CLI interface."""

    def print(self, message: str) -> None:
        timestamp = datetime.now().strftime("%X")
        if "\n" in message:
            message = message.replace("\n", f"\n{timestamp}: ")
        print(f"{timestamp}: {message}")


class ConsoleStatus:
    def update(self, status: str) -> None:
        print(f"[STATUS] {status}")


class ConsoleTray:
    def __init__(self, manager: ConsoleGUIManager):
        self._manager = manager
        self._icon: str = "pickaxe"

    def change_icon(self, icon: str) -> None:
        self._icon = icon
        logger.debug("Tray icon changed to %s", icon)

    def update_title(self, drop: Any | None) -> None:
        if drop is None:
            logger.debug("Tray title cleared")
        else:
            logger.debug("Tray title updated for drop: %s", drop)

    def restore(self) -> None:  # pragma: no cover - no GUI equivalent in CLI
        pass

    def stop(self) -> None:  # pragma: no cover - no GUI equivalent in CLI
        pass

    def minimize(self) -> None:  # pragma: no cover - no GUI equivalent in CLI
        pass

    def notify(self, message: str, title: str) -> None:
        if not self._manager._twitch.settings.tray_notifications:
            return
        print(f"[{title}] {message}")


class ConsoleChannelList:
    def __init__(self, manager: ConsoleGUIManager):
        self._manager = manager
        self._channels: dict[int, Any] = {}
        self._watching: Any | None = None

    def display(self, channel: Any, *, add: bool = False) -> None:
        self._channels[channel.id] = channel
        if add:
            logger.info("Tracking channel: %s", channel.name)

    def remove(self, channel: Any) -> None:
        self._channels.pop(channel.id, None)

    def clear(self) -> None:
        self._channels.clear()

    def clear_selection(self) -> None:  # pragma: no cover - CLI has no selection
        pass

    def set_watching(self, channel: Any) -> None:
        self._watching = channel

    def clear_watching(self) -> None:
        self._watching = None

    def get_selection(self) -> Any | None:
        return None


class ConsoleProgress:
    def __init__(self):
        self._drop = None
        self._timer_started: float | None = None

    def display(self, drop: Any | None, *, countdown: bool = True, subone: bool = False) -> None:
        self._drop = drop
        self.stop_timer()
        if drop is None:
            print("No active drop.")
            return
        minutes = getattr(drop, "current_minutes", 0)
        required = getattr(drop, "required_minutes", 0)
        game = getattr(drop.campaign, "game", None)
        game_name = game.name if isinstance(game, Game) else str(game)
        print(
            f"Drop progress: {drop.name} ({game_name}) {minutes}/{required} minutes"
        )
        if countdown:
            self.start_timer()

    def start_timer(self) -> None:
        self._timer_started = monotonic()

    def stop_timer(self) -> None:
        self._timer_started = None

    def minute_almost_done(self) -> bool:
        if self._timer_started is None:
            return True
        return monotonic() - self._timer_started >= 50


class ConsoleInventory:
    def __init__(self, manager: ConsoleGUIManager):
        self._manager = manager

    async def add_campaign(self, campaign: Any) -> None:
        print(f"New campaign available: {campaign.name} ({campaign.game.name})")

    def update_drop(self, drop: Any) -> None:
        logger.debug("Drop updated: %s", drop)

    def clear(self) -> None:
        pass


class ConsoleLoginForm:
    def __init__(self, manager: ConsoleGUIManager):
        self._manager = manager
        self._status: str = ""

    def update(self, status: str, user_id: int | None) -> None:
        if user_id is not None:
            self._status = f"{status}\n{user_id}"
        else:
            self._status = status
        print(self._status)

    def clear(self, login: bool = False, password: bool = False, token: bool = False) -> None:
        # Nothing to clear in CLI mode
        pass

    async def ask_login(self) -> LoginData:
        loop = asyncio.get_running_loop()
        username = await loop.run_in_executor(None, lambda: input("Twitch username: ").strip())

        def _read_password() -> str:
            return getpass("Twitch password: ")

        password = await loop.run_in_executor(None, _read_password)

        token = await loop.run_in_executor(None, lambda: input("2FA code (optional): ").strip())
        return LoginData(username=username, password=password, token=token)

    async def ask_enter_code(self, page_url, user_code: str) -> None:
        print(
            "Enter the following code on Twitch's activation page: "
            f"{user_code} ({page_url})"
        )
        await asyncio.sleep(1)
        webopen(page_url)


class ConsoleGUIManager:
    """Drop-in replacement for the GUI manager that prints to stdout."""

    def __init__(self, twitch):
        self._twitch = twitch
        self.tray = ConsoleTray(self)
        self.status = ConsoleStatus()
        self.output = ConsoleOutput()
        self.channels = ConsoleChannelList(self)
        self.progress = ConsoleProgress()
        self.inv = ConsoleInventory(self)
        self.login = ConsoleLoginForm(self)
        self._close_requested = False
        self._hold_open = False
        logger = logging.getLogger("TwitchDrops")
        if not any(getattr(handler, "_tdm_cli", False) for handler in logger.handlers):
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )
            handler._tdm_cli = True  # type: ignore[attr-defined]
            logger.addHandler(handler)

    def prevent_close(self) -> None:
        self._hold_open = True
        self._close_requested = False

    def print(self, message: str) -> None:
        self.output.print(message)

    def save(self, *, force: bool = False) -> None:  # pragma: no cover - nothing to save
        pass

    def start(self) -> None:  # pragma: no cover - nothing to start
        pass

    def stop(self) -> None:  # pragma: no cover - nothing to stop
        self.progress.stop_timer()

    def grab_attention(self, *, sound: bool = True) -> None:
        if sound:
            print("\a", end="")

    def set_games(self, games: Iterable[Game]) -> None:
        game_names = sorted({game.name for game in games})
        if game_names:
            print(
                "Loaded games: "
                + ", ".join(game_names)
            )

    def display_drop(self, drop: Any, *, countdown: bool = True, subone: bool = False) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)

    def clear_drop(self) -> None:
        self.progress.display(None)

    async def wait_until_closed(self) -> None:
        if self._hold_open:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: input("Press Enter to exit..."))
        self._hold_open = False

    def close(self, *args) -> int:
        self._close_requested = True
        self._twitch.close()
        return 0

    def close_window(self) -> None:  # pragma: no cover - nothing to close
        pass

    async def coro_unless_closed(self, coro: Any):
        if self._close_requested:
            from exceptions import ExitRequest

            raise ExitRequest()
        return await coro

    @property
    def close_requested(self) -> bool:
        return self._close_requested

