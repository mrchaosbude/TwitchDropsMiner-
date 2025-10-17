from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

# Ensure the original project root is importable and treated as the working dir.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Point argv[0] at main.py so constants.WORKING_DIR resolves to the project root.
if not os.environ.get("TWITCH_MINER_KEEP_ARGV"):
    sys.argv[0] = str(PROJECT_ROOT.joinpath("main.py"))

os.chdir(PROJECT_ROOT)

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
except ModuleNotFoundError as exc:  # pragma: no cover - fastapi is optional
    raise SystemExit(
        "FastAPI dependencies are missing. Install optional requirements via"
        " 'pip install -r requirements.txt' before running the web wrapper."
    ) from exc

try:
    import uvicorn
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
    raise SystemExit(
        "Uvicorn is missing. Install optional requirements via"
        " 'pip install -r requirements.txt' before running the web wrapper."
    ) from exc

try:
    import truststore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    truststore = None

from constants import (
    FILE_FORMATTER,
    LOCK_PATH,
    LOG_PATH,
    LOGGING_LEVELS,
    SELF_PATH,
    State,
)
from exceptions import CaptchaRequired
from settings import Settings
from translate import _
from utils import lock_file
from version import __version__

# Install the headless GUI adapter before importing twitch
from web_wrapper import headless_gui

sys.modules.setdefault("gui", headless_gui)

from twitch import Twitch  # noqa: E402


class ParsedArgs(argparse.Namespace):
    _verbose: int
    _debug_ws: bool
    _debug_gql: bool
    log: bool
    tray: bool
    dump: bool
    host: str
    port: int

    @property
    def logging_level(self) -> int:
        return LOGGING_LEVELS[min(self._verbose, 4)]

    @property
    def debug_ws(self) -> int:
        if self._debug_ws:
            return logging.DEBUG
        if self._verbose >= 4:
            return logging.INFO
        return logging.NOTSET

    @property
    def debug_gql(self) -> int:
        if self._debug_gql:
            return logging.DEBUG
        if self._verbose >= 4:
            return logging.INFO
        return logging.NOTSET


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        SELF_PATH.name,
        description="Headless Twitch Drops Miner web wrapper.",
    )
    parser.add_argument("--version", action="version", version=f"v{__version__}")
    parser.add_argument("-v", dest="_verbose", action="count", default=0)
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument(
        "--debug-ws", dest="_debug_ws", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--debug-gql", dest="_debug_gql", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument("--host", default="0.0.0.0", help="Web server host address")
    parser.add_argument("--port", type=int, default=8000, help="Web server port")
    return parser


def configure_logging(args: ParsedArgs) -> None:
    logging.getLogger().addHandler(logging.NullHandler())
    logger = logging.getLogger("TwitchDrops")
    logger.setLevel(args.logging_level)
    if args.log:
        handler = logging.FileHandler(LOG_PATH)
        handler.setFormatter(FILE_FORMATTER)
        logger.addHandler(handler)
    logging.getLogger("TwitchDrops.gql").setLevel(args.debug_gql)
    logging.getLogger("TwitchDrops.websocket").setLevel(args.debug_ws)


def create_app(client: Twitch) -> FastAPI:
    app = FastAPI(title="Twitch Drops Miner Web UI", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/state")
    async def get_state() -> JSONResponse:
        return JSONResponse(client.gui.state.snapshot())

    @app.post("/login/credentials")
    async def submit_login(payload: dict[str, Any]) -> JSONResponse:
        if not client.gui.login.waiting_for_credentials:
            raise HTTPException(status_code=409, detail="No pending login request")
        try:
            username = payload["username"]
            password = payload["password"]
            token = payload.get("token", "")
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"Missing field: {exc.args[0]}") from exc
        client.gui.login.submit_credentials(username, password, token)
        client.gui.print(_("gui", "login", "submitted"))
        return JSONResponse({"status": "ok"})

    @app.post("/login/device")
    async def confirm_device_code() -> JSONResponse:
        if not client.gui.login.waiting_for_device_code:
            raise HTTPException(status_code=409, detail="No pending device code request")
        client.gui.login.confirm_device_code()
        client.gui.print(_("gui", "login", "device_confirm"))
        return JSONResponse({"status": "ok"})

    @app.post("/channels/switch")
    async def switch_channel(payload: dict[str, Any]) -> JSONResponse:
        channel_id = payload.get("channel_id")
        if not isinstance(channel_id, str):
            raise HTTPException(status_code=400, detail="channel_id must be provided")
        try:
            client.gui.channels.select(channel_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found") from exc
        client.change_state(State.CHANNEL_SWITCH)
        return JSONResponse({"status": "ok"})

    @app.post("/shutdown")
    async def shutdown() -> JSONResponse:
        client.gui.print("Shutdown requested via API")
        client.gui.close()
        return JSONResponse({"status": "ok"})

    @app.post("/notifications/clear")
    async def clear_notifications() -> JSONResponse:
        client.gui.state.notifications.clear()
        return JSONResponse({"status": "ok"})

    return app


async def run_client(client: Twitch) -> int:
    exit_status = 0
    try:
        await client.run()
    except CaptchaRequired:
        exit_status = 1
        client.prevent_close()
        client.print(_("error", "captcha"))
    except Exception:  # noqa: BLE001 - surface fatal error in output
        exit_status = 1
        client.prevent_close()
        client.print("Fatal error encountered:\n")
        client.print(traceback.format_exc())
    finally:
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


async def serve(args: ParsedArgs) -> int:
    if truststore is not None:
        truststore.inject_into_ssl()
    configure_logging(args)
    try:
        settings = Settings(args)
    except Exception as exc:  # noqa: BLE001 - propagate error to logs
        print(f"Error while loading settings: {exc}", file=sys.stderr)
        return 4

    lock_ok, lock_handle = lock_file(LOCK_PATH)
    if not lock_ok:
        return 3

    client = Twitch(settings)
    app = create_app(client)
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_config=None,
        loop="asyncio",
        lifespan="off",
    )
    server = uvicorn.Server(config)

    async def uvicorn_task() -> None:
        await server.serve()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, client.gui.close)
        loop.add_signal_handler(signal.SIGTERM, client.gui.close)

    try:
        client_task = asyncio.create_task(run_client(client))
        server_task = asyncio.create_task(uvicorn_task())
        done, pending = await asyncio.wait(
            {client_task, server_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if server_task in done and not client_task.done():
            client.gui.close()
        if client_task in done and not server.should_exit:
            server.should_exit = True
        await asyncio.gather(*pending, return_exceptions=True)
        exit_status = client_task.result() if client_task.done() else 0
    finally:
        if sys.platform != "win32":
            loop.remove_signal_handler(signal.SIGINT)
            loop.remove_signal_handler(signal.SIGTERM)
        if lock_handle:
            with suppress(Exception):
                lock_handle.close()
    return exit_status


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(namespace=ParsedArgs())
    return asyncio.run(serve(args))


if __name__ == "__main__":
    raise SystemExit(main())

