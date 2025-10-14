"""Headless command line entry point for Twitch Drops Miner."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import traceback
import warnings
from pathlib import Path
from multiprocessing import freeze_support
from typing import Mapping, Sequence, TypedDict

try:
    import truststore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    truststore = None

from version import __version__


WRAPPER_SETTINGS_FILENAME = "cli_wrapper_settings.json"
UNEXPECTED_RESTART_DELAY = 30


class WrapperConfig(TypedDict):
    verbose: int
    quiet: bool
    log: bool
    dump: bool
    tray: bool
    telegram_token: str
    telegram_chat_id: str
    telegram_thread_id: int | None
    telegram_commands: bool


DEFAULT_WRAPPER_CONFIG: WrapperConfig = {
    "verbose": 0,
    "quiet": False,
    "log": False,
    "dump": False,
    "tray": False,
    "telegram_token": "",
    "telegram_chat_id": "",
    "telegram_thread_id": None,
    "telegram_commands": False,
}


class ParsedArgs(argparse.Namespace):
    _verbose: int
    _debug_ws: bool
    _debug_gql: bool
    log: bool
    tray: bool
    dump: bool
    quiet: bool
    telegram_token: str | None
    telegram_chat_id: str | None
    telegram_thread_id: int | None
    telegram_commands: bool

    @property
    def logging_level(self) -> int:
        from constants import LOGGING_LEVELS

        return LOGGING_LEVELS[min(self._verbose, 4)]

    @property
    def debug_ws(self) -> int:
        import logging as _logging

        level = self.logging_level
        if self._debug_ws:
            return _logging.DEBUG
        if level <= _logging.DEBUG:
            return _logging.INFO
        return _logging.NOTSET

    @property
    def debug_gql(self) -> int:
        import logging as _logging

        level = self.logging_level
        if self._debug_gql:
            return _logging.DEBUG
        if level <= _logging.DEBUG:
            return _logging.INFO
        return _logging.NOTSET


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run Twitch Drops Miner in a headless environment without launching the GUI."
        )
    )
    parser.add_argument("--version", action="version", version=f"v{__version__}")
    parser.add_argument(
        "-v", dest="_verbose", action="count", default=0, help="Increase console verbosity"
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only show warnings and errors in the console output",
    )
    parser.add_argument("--tray", action="store_true", help="(ignored) kept for compatibility")
    parser.add_argument("--log", action="store_true", help="Write log output to twitch.log")
    parser.add_argument("--dump", action="store_true", help="Reset debug dump file on start")
    parser.add_argument(
        "--debug-ws", dest="_debug_ws", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--debug-gql", dest="_debug_gql", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--telegram-token",
        help="Telegram bot token used to send notifications when a drop is mined",
    )
    parser.add_argument(
        "--telegram-chat-id",
        help="Telegram chat ID that should receive mined drop notifications",
    )
    parser.add_argument(
        "--telegram-thread-id",
        type=int,
        help=(
            "Optional Telegram forum topic/thread identifier to target when sending"
            " notifications"
        ),
    )
    parser.add_argument(
        "--telegram-commands",
        action="store_true",
        help=(
            "Enable Telegram bot commands to inspect and update CLI wrapper settings"
        ),
    )
    return parser


def _wrapper_settings_path() -> Path:
    from constants import WORKING_DIR

    return Path(WORKING_DIR, WRAPPER_SETTINGS_FILENAME)


def _coerce_wrapper_config(data: Mapping[str, object]) -> WrapperConfig:
    config: WrapperConfig = dict(DEFAULT_WRAPPER_CONFIG)

    try:
        verbose = int(data.get("verbose", config["verbose"]))
    except (TypeError, ValueError):
        verbose = config["verbose"]
    config["verbose"] = max(0, verbose)

    for key in ("quiet", "log", "dump", "tray"):
        value = data.get(key, config[key])
        if isinstance(value, bool):
            config[key] = value
        elif isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                config[key] = True
            elif lowered in {"0", "false", "no", "off"}:
                config[key] = False

    token = data.get("telegram_token", config["telegram_token"])
    if token is None:
        config["telegram_token"] = ""
    else:
        config["telegram_token"] = str(token).strip()

    chat_id = data.get("telegram_chat_id", config["telegram_chat_id"])
    if chat_id is None:
        config["telegram_chat_id"] = ""
    else:
        config["telegram_chat_id"] = str(chat_id).strip()

    thread_id = data.get("telegram_thread_id", config["telegram_thread_id"])
    if thread_id in {"", None}:
        config["telegram_thread_id"] = None
    else:
        try:
            config["telegram_thread_id"] = int(thread_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            config["telegram_thread_id"] = None

    return config


def load_wrapper_config() -> tuple[WrapperConfig, Path, bool]:
    from utils import json_load, json_save

    path = _wrapper_settings_path()
    existed = path.exists()
    raw_config = json_load(path, DEFAULT_WRAPPER_CONFIG)
    config = _coerce_wrapper_config(raw_config)
    if not existed:
        json_save(path, config, sort=True)
    return config, path, not existed


def apply_wrapper_config(args: ParsedArgs, config: WrapperConfig) -> set[str]:
    applied: set[str] = set()

    if args._verbose == 0 and config["verbose"] > 0:
        args._verbose = config["verbose"]
        applied.add("verbose")

    if not args.quiet and config["quiet"]:
        args.quiet = True
        applied.add("quiet")

    if not args.log and config["log"]:
        args.log = True
        applied.add("log")

    if not args.dump and config["dump"]:
        args.dump = True
        applied.add("dump")

    if not args.tray and config["tray"]:
        args.tray = True
        applied.add("tray")

    if args.telegram_token is None:
        token = config["telegram_token"].strip()
        if token:
            args.telegram_token = token
            applied.add("telegram_token")

    if args.telegram_chat_id is None:
        chat_id = config["telegram_chat_id"].strip()
        if chat_id:
            args.telegram_chat_id = chat_id
            applied.add("telegram_chat_id")

    if args.telegram_thread_id is None and config["telegram_thread_id"] is not None:
        args.telegram_thread_id = config["telegram_thread_id"]
        applied.add("telegram_thread_id")

    if not args.telegram_commands and config["telegram_commands"]:
        args.telegram_commands = True
        applied.add("telegram_commands")

    return applied


class WrapperSettingsManager:
    """Expose wrapper configuration operations for Telegram commands."""

    def __init__(self, path: Path):
        self._path = path

    def _load_raw(self) -> Mapping[str, object]:
        from utils import json_load

        return json_load(self._path, DEFAULT_WRAPPER_CONFIG)

    def list_options(self) -> WrapperConfig:
        return _coerce_wrapper_config(self._load_raw())

    def update_option(self, key: str, value: str) -> tuple[bool, str]:
        from utils import json_save

        if key not in DEFAULT_WRAPPER_CONFIG:
            return False, f"Unknown option '{key}'"

        raw = dict(self._load_raw())
        raw[key] = value
        config = _coerce_wrapper_config(raw)
        json_save(self._path, config, sort=True)
        rendered = config[key]
        if isinstance(rendered, bool):
            rendered_text = "on" if rendered else "off"
        else:
            rendered_text = str(rendered)
        return True, f"Updated {key} -> {rendered_text}"


def patch_headless_gui(args: ParsedArgs, *, settings_manager: WrapperSettingsManager | None) -> None:
    from headless_gui import HeadlessGUI, configure_telegram
    import sys
    from types import ModuleType

    configure_telegram(
        token=args.telegram_token,
        chat_id=args.telegram_chat_id,
        thread_id=args.telegram_thread_id,
        settings_manager=settings_manager if args.telegram_commands else None,
    )
    module = sys.modules.get("gui")
    if module is None:
        module = ModuleType("gui")
        sys.modules["gui"] = module
    module.GUIManager = HeadlessGUI


def configure_logging(args: ParsedArgs) -> int:
    console_level = (
        logging.WARNING if args.quiet else min(args.logging_level, logging.INFO)
    )
    logging.basicConfig(
        level=console_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    return console_level


async def run_client(args: ParsedArgs) -> int:
    from settings import Settings
    from exceptions import CaptchaRequired, GQLException
    from translate import _
    from constants import FILE_FORMATTER, LOG_PATH, PriorityMode, SETTINGS_PATH

    wrapper_config, config_path, created = load_wrapper_config()
    settings_manager = WrapperSettingsManager(config_path)
    applied = apply_wrapper_config(args, wrapper_config)

    console_level = configure_logging(args)
    bootstrap_logger = logging.getLogger("TwitchDrops.bootstrap")
    bootstrap_logger.setLevel(console_level)
    if created:
        bootstrap_logger.info(
            "Created CLI wrapper settings template at %s", config_path
        )
    else:
        bootstrap_logger.info("Loaded CLI wrapper settings from %s", config_path)
    if applied:
        bootstrap_logger.info(
            "Applied stored wrapper options: %s", ", ".join(sorted(applied))
        )
    bootstrap_logger.info("Starting Twitch Drops Miner in headless mode")

    if args.telegram_commands:
        bootstrap_logger.info(
            "Telegram command interface enabled; send /help to your bot for usage"
        )

    while True:
        try:
            bootstrap_logger.info("Loading settings from %s", SETTINGS_PATH)
            settings = Settings(args)
        except Exception:
            print("There was an error while loading the settings file:", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            return 4

        if not settings.priority and settings.priority_mode is PriorityMode.PRIORITY_ONLY:
            bootstrap_logger.info(
                "No priority campaigns configured; enabling automatic campaign selection"
            )
            settings.priority_mode = PriorityMode.ENDING_SOONEST

        # Ensure the GUI class used by Twitch is replaced before the client is created.
        patch_headless_gui(
            args,
            settings_manager=settings_manager,
        )

        from twitch import Twitch

        if truststore is not None:
            truststore.inject_into_ssl()
        else:
            logging.warning(
                "truststore package is missing; using system certificate store"
            )

        if settings.tray:
            logging.warning(
                "Tray mode is not supported in headless operation; ignoring --tray"
            )
            settings.tray = False

        # Configure logging according to settings.
        if settings.logging_level > logging.DEBUG:
            logging.getLogger().addHandler(logging.NullHandler())
        logger = logging.getLogger("TwitchDrops")
        logger.setLevel(console_level)
        if settings.log:
            handler = logging.FileHandler(LOG_PATH)
            handler.setFormatter(FILE_FORMATTER)
            handler.setLevel(settings.logging_level)
            logger.addHandler(handler)
            bootstrap_logger.info("Writing persistent logs to %s", LOG_PATH)
        else:
            bootstrap_logger.debug(
                "File logging disabled; pass --log to enable it"
            )
        logging.getLogger("TwitchDrops.gql").setLevel(settings.debug_gql)
        logging.getLogger("TwitchDrops.websocket").setLevel(settings.debug_ws)

        bootstrap_logger.info("Initialising Twitch client")
        client = Twitch(settings)
        bootstrap_logger.info("Twitch client initialised; starting event loop")

        loop = asyncio.get_running_loop()
        if sys.platform == "linux":
            loop.add_signal_handler(signal.SIGINT, lambda *_: client.gui.close())
            loop.add_signal_handler(signal.SIGTERM, lambda *_: client.gui.close())

        exit_status = 0
        transient_restart_reason: str | None = None
        try:
            bootstrap_logger.info("Miner is running; press Ctrl+C to exit")
            await client.run()
        except CaptchaRequired:
            exit_status = 1
            client.prevent_close()
            client.print(_("error", "captcha"))
            bootstrap_logger.error(
                "Twitch requires captcha verification; complete it and restart the miner"
            )
        except GQLException as exc:
            exit_status = 1
            transient_restart_reason = "Twitch service error"
            client.prevent_close()
            client.print("Twitch reported a temporary service error. The miner will retry shortly.\n")
            client.print(str(exc))
            client.gui.status.update("Service error – retrying shortly")
            bootstrap_logger.error(
                "GraphQL service error encountered; scheduling automatic restart",
                exc_info=exc,
            )
        except Exception:
            exit_status = 1
            client.prevent_close()
            client.print("Fatal error encountered:\n")
            client.print(traceback.format_exc())
            bootstrap_logger.exception("Fatal error in Twitch Drops Miner")
        finally:
            if sys.platform == "linux":
                loop.remove_signal_handler(signal.SIGINT)
                loop.remove_signal_handler(signal.SIGTERM)
            client.print(_("gui", "status", "exiting"))
            bootstrap_logger.info("Stopping miner and cleaning up")
            await client.shutdown()

        unexpected_stop = not client.gui.close_requested
        auto_restart = unexpected_stop and (
            exit_status == 0 or transient_restart_reason is not None
        )

        if unexpected_stop and not auto_restart:
            client.gui.tray.change_icon("error")
            client.print(_("status", "terminated"))
            client.gui.status.update(_("gui", "status", "terminated"))
            client.gui.grab_attention(sound=True)
            bootstrap_logger.warning(
                "Miner terminated unexpectedly; attention requested"
            )

        if auto_restart:
            if transient_restart_reason is None:
                client.print("Miner stopped unexpectedly; restarting automatically.")
                bootstrap_logger.warning(
                    "Miner stopped without a shutdown request; restarting"
                )
            else:
                client.print(
                    "Miner encountered a temporary Twitch error and will restart automatically."
                )
                bootstrap_logger.warning(
                    "Miner stopped because of a transient Twitch service error; restarting"
                )

        await client.gui.wait_until_closed()
        client.save(force=True)
        client.gui.stop()
        client.gui.close_window()

        if exit_status == 0:
            bootstrap_logger.info("Twitch Drops Miner stopped successfully")
        elif transient_restart_reason is not None:
            bootstrap_logger.warning(
                "Twitch Drops Miner stopped because of a transient error: %s",
                transient_restart_reason,
            )
        else:
            bootstrap_logger.error(
                "Twitch Drops Miner exited with status %s", exit_status
            )

        if auto_restart:
            bootstrap_logger.info(
                "Restarting miner automatically in %s seconds",
                UNEXPECTED_RESTART_DELAY,
            )
            await asyncio.sleep(UNEXPECTED_RESTART_DELAY)
            continue

        return exit_status


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv, namespace=ParsedArgs())

    warnings.simplefilter("default", ResourceWarning)

    from utils import lock_file
    from constants import LOCK_PATH

    success, lock = lock_file(LOCK_PATH)
    if not success:
        print("Another Twitch Drops Miner instance is already running.", file=sys.stderr)
        return 3

    try:
        return asyncio.run(run_client(args))
    finally:
        lock.close()


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
