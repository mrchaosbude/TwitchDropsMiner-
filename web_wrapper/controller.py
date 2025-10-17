"""Controller that runs the Twitch Drops miner in a headless environment."""
from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from contextlib import suppress
from typing import Any, Optional

import truststore

# Ensure certificates are configured the same way as the desktop app.
truststore.inject_into_ssl()

from . import headless_gui

# Replace the Tk-based GUI module with the headless adapter before anything imports it.
sys.modules["gui"] = headless_gui

from constants import LOCK_PATH, LOGGING_LEVELS, PriorityMode
from exceptions import CaptchaRequired
from settings import Settings
from twitch import Twitch
from utils import lock_file
from translate import _

logger = logging.getLogger(__name__)


class WebArguments:
    """Argument namespace that mimics :class:`main.ParsedArgs`."""

    def __init__(
        self,
        *,
        verbose: int = 0,
        log: bool = False,
        tray: bool = False,
        dump: bool = False,
        debug_ws: bool = False,
        debug_gql: bool = False,
    ) -> None:
        self._verbose = verbose
        self._debug_ws = debug_ws
        self._debug_gql = debug_gql
        self.log = log
        self.tray = tray
        self.dump = dump

    @property
    def logging_level(self) -> int:
        return LOGGING_LEVELS[min(self._verbose, 4)]

    @property
    def debug_ws(self) -> int:
        return logging.DEBUG if self._debug_ws else logging.NOTSET

    @property
    def debug_gql(self) -> int:
        return logging.DEBUG if self._debug_gql else logging.NOTSET


class MinerController:
    def __init__(self) -> None:
        self._args = WebArguments()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._twitch: Twitch | None = None
        self._lock_handle = None
        self._fallback_state = headless_gui.HeadlessState()

    @property
    def twitch(self) -> Twitch | None:
        return self._twitch

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        async with self._lock:
            if self.is_running():
                raise RuntimeError("Miner is already running")
            success, handle = lock_file(LOCK_PATH)
            if not success:
                handle.close()
                raise RuntimeError("Another miner instance is already running")
            self._lock_handle = handle
            settings = Settings(self._args)
            self._twitch = Twitch(settings)
            self._fallback_state = self._twitch.gui.state
            self._task = asyncio.create_task(self._runner())

    async def stop(self) -> None:
        async with self._lock:
            if self._twitch is None:
                return
            self._twitch.gui.close()
            if self._task is not None:
                with suppress(asyncio.CancelledError):
                    await self._task
            self._task = None
            self._cleanup_after_run()

    async def _runner(self) -> None:
        assert self._twitch is not None
        client = self._twitch
        try:
            await client.run()
        except CaptchaRequired:
            client.prevent_close()
            client.print(_("error", "captcha"))
            client.gui.notify_error("Captcha required. Complete verification in the browser.")
        except Exception as exc:  # pragma: no cover - defensive
            client.prevent_close()
            message = "Fatal error encountered:\n" + traceback.format_exc()
            client.print(message)
            client.gui.notify_error(str(exc))
            logger.exception("Miner crashed")
        finally:
            await client.shutdown()
            client.save(force=True)
            client.gui.stop()
            client.gui.close_window()
            self._cleanup_after_run()

    def _cleanup_after_run(self) -> None:
        if self._lock_handle is not None:
            with suppress(Exception):
                self._lock_handle.close()
            self._lock_handle = None
        if self._twitch is not None:
            self._fallback_state = self._twitch.gui.state
            self._twitch = None

    def state_snapshot(self) -> dict[str, Any]:
        if self._twitch is not None:
            return self._twitch.gui.state.snapshot()
        return self._fallback_state.snapshot()

    def submit_login(self, username: str, password: str, token: str = "") -> None:
        if self._twitch is None:
            raise RuntimeError("Miner is not running")
        self._twitch.gui.login.submit_credentials(username, password, token)

    def select_channel(self, channel_id: Optional[int]) -> None:
        if self._twitch is None:
            raise RuntimeError("Miner is not running")
        self._twitch.gui.select_channel(channel_id)

    def get_settings(self) -> Settings:
        if self._twitch is not None:
            return self._twitch.settings
        return Settings(self._args)

    def settings_snapshot(self) -> dict[str, Any]:
        settings = self.get_settings()
        data = {
            "proxy": str(settings.proxy),
            "language": settings.language,
            "dark_mode": settings.dark_mode,
            "exclude": sorted(settings.exclude),
            "priority": list(settings.priority),
            "autostart_tray": settings.autostart_tray,
            "connection_quality": settings.connection_quality,
            "tray_notifications": settings.tray_notifications,
            "priority_mode": settings.priority_mode.name,
            "log": settings.log,
            "tray": settings.tray,
            "dump": settings.dump,
        }
        return data

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        settings = self.get_settings()
        for key, value in updates.items():
            if key == "language" and value is not None:
                settings.language = value
            elif key == "dark_mode" and value is not None:
                settings.dark_mode = bool(value)
            elif key == "exclude" and value is not None:
                settings.exclude = set(value)
            elif key == "priority" and value is not None:
                settings.priority = list(value)
            elif key == "connection_quality" and value is not None:
                settings.connection_quality = int(value)
            elif key == "tray_notifications" and value is not None:
                settings.tray_notifications = bool(value)
            elif key == "priority_mode" and value is not None:
                settings.priority_mode = PriorityMode[value]
        settings.save(force=True)
        return self.settings_snapshot()


__all__ = ["MinerController", "WebArguments"]
