"""Headless command line entry point for Twitch Drops Miner."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import traceback
import warnings
from multiprocessing import freeze_support
from typing import Sequence

try:
    import truststore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    truststore = None

from version import __version__


class ParsedArgs(argparse.Namespace):
    _verbose: int
    _debug_ws: bool
    _debug_gql: bool
    log: bool
    tray: bool
    dump: bool

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
    parser.add_argument("--tray", action="store_true", help="(ignored) kept for compatibility")
    parser.add_argument("--log", action="store_true", help="Write log output to twitch.log")
    parser.add_argument("--dump", action="store_true", help="Reset debug dump file on start")
    parser.add_argument(
        "--debug-ws", dest="_debug_ws", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--debug-gql", dest="_debug_gql", action="store_true", help=argparse.SUPPRESS
    )
    return parser


def patch_headless_gui() -> None:
    from headless_gui import HeadlessGUI
    import gui

    gui.GUIManager = HeadlessGUI


def configure_logging(args: ParsedArgs) -> None:
    level = args.logging_level
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def run_client(args: ParsedArgs) -> int:
    from settings import Settings
    from exceptions import CaptchaRequired
    from translate import _
    from constants import FILE_FORMATTER, LOG_PATH

    configure_logging(args)

    try:
        settings = Settings(args)
    except Exception:
        print("There was an error while loading the settings file:", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return 4

    # Ensure the GUI class used by Twitch is replaced before the client is created.
    patch_headless_gui()

    from twitch import Twitch

    if truststore is not None:
        truststore.inject_into_ssl()
    else:
        logging.warning("truststore package is missing; using system certificate store")

    if settings.tray:
        logging.warning("Tray mode is not supported in headless operation; ignoring --tray")
        settings.tray = False

    # Configure logging according to settings.
    if settings.logging_level > logging.DEBUG:
        logging.getLogger().addHandler(logging.NullHandler())
    logger = logging.getLogger("TwitchDrops")
    logger.setLevel(settings.logging_level)
    if settings.log:
        handler = logging.FileHandler(LOG_PATH)
        handler.setFormatter(FILE_FORMATTER)
        logger.addHandler(handler)
    logging.getLogger("TwitchDrops.gql").setLevel(settings.debug_gql)
    logging.getLogger("TwitchDrops.websocket").setLevel(settings.debug_ws)

    client = Twitch(settings)

    loop = asyncio.get_running_loop()
    if sys.platform == "linux":
        loop.add_signal_handler(signal.SIGINT, lambda *_: client.gui.close())
        loop.add_signal_handler(signal.SIGTERM, lambda *_: client.gui.close())

    exit_status = 0
    try:
        await client.run()
    except CaptchaRequired:
        exit_status = 1
        client.prevent_close()
        client.print(_("error", "captcha"))
    except Exception:
        exit_status = 1
        client.prevent_close()
        client.print("Fatal error encountered:\n")
        client.print(traceback.format_exc())
    finally:
        if sys.platform == "linux":
            loop.remove_signal_handler(signal.SIGINT)
            loop.remove_signal_handler(signal.SIGTERM)
        client.print(_("gui", "status", "exiting"))
        await client.shutdown()

    if not client.gui.close_requested:
        client.gui.tray.change_icon("error")
        client.print(_("status", "terminated"))
        client.gui.status.update(_("gui", "status", "terminated"))
        client.gui.grab_attention(sound=True)

    await client.gui.wait_until_closed()
    client.save(force=True)
    client.gui.stop()
    client.gui.close_window()

    return exit_status


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv, namespace=ParsedArgs())

    warnings.simplefilter("default", ResourceWarning)

    from utils import lock_file
    from constants import LOCK_PATH

    success, lock = lock_file(LOCK_PATH)
    if not success:
        return 3

    try:
        return asyncio.run(run_client(args))
    finally:
        lock.close()


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
