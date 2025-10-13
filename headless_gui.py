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
from typing import Any, Awaitable, Dict, Mapping, Optional, Protocol, Set

import aiohttp
from yarl import URL

logger = logging.getLogger("TwitchDrops")


@dataclass
class LoginData:
    """Simple container matching the GUI login data structure."""

    username: str
    password: str
    token: str


@dataclass
class TelegramConfig:
    token: str
    chat_id: str
    thread_id: int | None = None
    timeout: float = 10.0


class TelegramSettingsManager(Protocol):
    def list_options(self) -> Mapping[str, Any]:
        ...

    def update_option(self, key: str, value: str) -> tuple[bool, str]:
        ...


_telegram_config: TelegramConfig | None = None
_telegram_listener: "_TelegramCommandListener" | None = None
_telegram_stop_waiter: asyncio.Task[None] | None = None


def configure_telegram(
    *,
    token: str | None,
    chat_id: str | None,
    thread_id: int | None,
    settings_manager: TelegramSettingsManager | None = None,
) -> None:
    """Configure Telegram notifications for headless mode."""

    global _telegram_config, _telegram_listener, _telegram_stop_waiter

    _stop_telegram_listener()

    if token and chat_id:
        _telegram_config = TelegramConfig(
            token=token.strip(),
            chat_id=chat_id.strip(),
            thread_id=thread_id,
        )
        logger.info("Telegram notifications enabled for chat %s", _telegram_config.chat_id)
        if settings_manager is not None:
            _start_telegram_listener(settings_manager)
    else:
        if (token and not chat_id) or (chat_id and not token):
            logger.warning(
                "Incomplete Telegram configuration provided; notifications will be disabled"
            )
        if _telegram_config is not None:
            logger.info("Telegram notifications disabled")
        _telegram_config = None

        if settings_manager is not None:
            logger.warning(
                "Telegram commands requested but Telegram is not configured; ignoring"
            )


def _start_telegram_listener(settings_manager: TelegramSettingsManager) -> None:
    global _telegram_listener, _telegram_stop_waiter

    if _telegram_config is None:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Telegram commands require an active event loop; disabling")
        return

    listener = _TelegramCommandListener(_telegram_config, settings_manager)
    listener.start(loop)
    _telegram_listener = listener
    _telegram_stop_waiter = None


def _stop_telegram_listener() -> None:
    global _telegram_listener, _telegram_stop_waiter

    listener = _telegram_listener
    if listener is None:
        task = _telegram_stop_waiter
        if task is not None and task.done():
            try:
                task.result()
            except Exception:
                logger.exception("Error while stopping Telegram listener")
            _telegram_stop_waiter = None
        return

    _telegram_listener = None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(listener.stop())
        _telegram_stop_waiter = None
    else:
        _telegram_stop_waiter = loop.create_task(listener.stop())


async def _send_telegram_message(title: str, body: str) -> None:
    if _telegram_config is None:
        return

    payload: Dict[str, Any] = {
        "chat_id": _telegram_config.chat_id,
        "text": f"{title}\n\n{body}",
        "disable_notification": False,
    }
    if _telegram_config.thread_id is not None:
        payload["message_thread_id"] = _telegram_config.thread_id

    url = f"https://api.telegram.org/bot{_telegram_config.token}/sendMessage"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, timeout=_telegram_config.timeout
            ) as response:
                if response.status >= 400:
                    text = await response.text()
                    logger.error(
                        "Telegram notification failed with status %s: %s",
                        response.status,
                        text,
                    )
                else:
                    logger.info("Telegram notification sent")
    except Exception:
        logger.exception("Failed to send Telegram notification")


def _maybe_send_telegram(title: str, body: str) -> None:
    if _telegram_config is None:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_send_telegram_message(title, body))
    else:
        loop.create_task(_send_telegram_message(title, body))


class _TelegramCommandListener:
    def __init__(
        self, config: TelegramConfig, manager: TelegramSettingsManager
    ) -> None:
        self._config = config
        self._manager = manager
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self._offset: int | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._task is not None:
            return
        self._task = loop.create_task(self._run(), name="TelegramCommandListener")

    async def stop(self) -> None:
        self._stopped = True
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        assert _telegram_config is not None
        session = aiohttp.ClientSession()
        try:
            while not self._stopped:
                if not self._config.token:
                    await asyncio.sleep(5)
                    continue

                url = (
                    f"https://api.telegram.org/bot{self._config.token}/getUpdates"
                )
                params: Dict[str, Any] = {"timeout": 25}
                if self._offset is not None:
                    params["offset"] = self._offset
                try:
                    async with session.get(
                        url, params=params, timeout=self._config.timeout + 5
                    ) as response:
                        if response.status >= 400:
                            text = await response.text()
                            logger.error(
                                "Telegram getUpdates failed with status %s: %s",
                                response.status,
                                text,
                            )
                            await asyncio.sleep(5)
                            continue
                        payload = await response.json()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Error while polling Telegram updates")
                    await asyncio.sleep(5)
                    continue

                if not isinstance(payload, dict):
                    logger.error("Unexpected Telegram response: %r", payload)
                    await asyncio.sleep(5)
                    continue

                for update in payload.get("result", []):
                    update_id = int(update.get("update_id", 0))
                    self._offset = max(self._offset or 0, update_id) + 1
                    await self._handle_update(update)
        finally:
            await session.close()

    async def _handle_update(self, update: Dict[str, Any]) -> None:
        message = update.get("message") or update.get("channel_post")
        if not isinstance(message, dict):
            return

        chat = message.get("chat")
        if not isinstance(chat, dict):
            return

        chat_id = str(chat.get("id"))
        if chat_id != self._config.chat_id:
            return

        if (
            self._config.thread_id is not None
            and message.get("message_thread_id") != self._config.thread_id
        ):
            return

        text = message.get("text")
        if not isinstance(text, str) or not text.strip().startswith("/"):
            return

        await self._dispatch_command(text.strip())

    async def _dispatch_command(self, text: str) -> None:
        logger.info("[telegram] received command: %s", text)
        if text.startswith("/help"):
            await _send_telegram_message(
                "CLI wrapper help",
                (
                    "Available commands:\n"
                    "/help - show this message\n"
                    "/settings - list stored wrapper options\n"
                    "/set <option> <value> - update a wrapper option"
                ),
            )
            return

        if text.startswith("/settings"):
            options = self._manager.list_options()
            body_lines = ["Stored CLI wrapper options:"]
            for key, value in sorted(options.items()):
                body_lines.append(f"- {key}: {value}")
            await _send_telegram_message("CLI wrapper settings", "\n".join(body_lines))
            return

        if text.startswith("/set"):
            parts = text.split(maxsplit=2)
            if len(parts) < 3:
                await _send_telegram_message(
                    "CLI wrapper error",
                    "Usage: /set <option> <value>",
                )
                return
            key, value = parts[1], parts[2]
            success, message = self._manager.update_option(key, value)
            title = "CLI wrapper updated" if success else "CLI wrapper error"
            await _send_telegram_message(title, message)
            if success:
                if key == "telegram_commands":
                    options = self._manager.list_options()
                    if not bool(options.get("telegram_commands")):
                        _stop_telegram_listener()
                elif key in {"telegram_token", "telegram_chat_id", "telegram_thread_id"}:
                    self._refresh_runtime_config()
            return

        await _send_telegram_message(
            "CLI wrapper error",
            "Unknown command. Send /help for usage.",
        )

    def _refresh_runtime_config(self) -> None:
        options = self._manager.list_options()

        token = str(options.get("telegram_token", "")).strip()
        chat_id = str(options.get("telegram_chat_id", "")).strip()
        thread_raw = options.get("telegram_thread_id")
        thread_id: int | None
        if thread_raw in {None, ""}:
            thread_id = None
        else:
            try:
                thread_id = int(thread_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                thread_id = None

        global _telegram_config

        if not token or not chat_id:
            if _telegram_config is not None:
                logger.info("Telegram notifications disabled via settings update")
            _telegram_config = None
            self._config = TelegramConfig(token="", chat_id="", thread_id=None)
            self._offset = None
            _stop_telegram_listener()
            return

        new_config = TelegramConfig(token=token, chat_id=chat_id, thread_id=thread_id)
        _telegram_config = new_config
        self._config = new_config
        self._offset = None
        logger.info(
            "Telegram configuration refreshed (chat=%s thread=%s)",
            new_config.chat_id,
            new_config.thread_id if new_config.thread_id is not None else "-",
        )


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
        _maybe_send_telegram(title, body)

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
        previous = self._current_drop
        self._current_drop = drop
        if drop is None:
            if previous is not None:
                logger.info("[progress] cleared current drop")
                logger.info(
                    "[progress] no active drop – waiting for the next eligible campaign"
                )
            return

        try:
            rewards = drop.rewards_text()
        except AttributeError:
            rewards = str(drop)

        details: list[str] = []
        progress = getattr(drop, "progress", None)
        if isinstance(progress, (int, float)):
            details.append(f"{progress * 100:.1f}%")

        campaign = getattr(drop, "campaign", None)
        claimed = getattr(campaign, "claimed_drops", None) if campaign else None
        total = getattr(campaign, "total_drops", None) if campaign else None
        if isinstance(claimed, int) and isinstance(total, int) and total:
            details.append(f"{claimed}/{total}")

        if details:
            rewards = f"{rewards} ({', '.join(details)})"

        logger.info("[progress] %s", rewards)


class HeadlessChannelList(_BaseComponent):
    def __init__(self, manager: "HeadlessGUI") -> None:
        super().__init__(manager)
        self._selection: Any | None = None
        self._channels: list[Any] = []

    def display(self, channel: Any, *, add: bool = False) -> None:
        logger.info("[channel] %s", getattr(channel, "name", channel))
        if add and channel not in self._channels:
            self._channels.append(channel)
        elif not add:
            # Updates for existing channels should keep the ordering but ensure
            # the channel is tracked even if it was not previously seen.
            if channel not in self._channels:
                self._channels.append(channel)
        self._selection = channel

    def clear(self) -> None:
        self._selection = None
        self._channels.clear()
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

    def remove(self, channel: Any) -> None:
        try:
            self._channels.remove(channel)
        except ValueError:
            logger.debug("[channel] attempted to remove unknown channel %s", channel)
            return
        if self._selection is channel:
            self._selection = None
        logger.info("[channel] removed %s", getattr(channel, "name", channel))


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
        global _telegram_stop_waiter

        task = _telegram_stop_waiter
        if task is None:
            return None

        _telegram_stop_waiter = None
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error while stopping Telegram listener")
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
        _stop_telegram_listener()

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
