"""FastAPI application exposing the Twitch Drops Miner functionality."""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .controller import MinerController

app = FastAPI(title="Twitch Drops Miner Web Wrapper")
controller = MinerController()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    token: Optional[str] = None


class ChannelSelection(BaseModel):
    channel_id: Optional[int] = Field(default=None, description="Channel ID to focus")


class SettingsUpdate(BaseModel):
    language: Optional[str] = None
    dark_mode: Optional[bool] = None
    exclude: Optional[list[str]] = None
    priority: Optional[list[str]] = None
    connection_quality: Optional[int] = Field(default=None, ge=1, le=6)
    tray_notifications: Optional[bool] = None
    priority_mode: Optional[str] = Field(default=None, description="PriorityMode enum name")


@app.get("/state")
async def get_state() -> dict:
    """Return a snapshot of the miner state."""
    return controller.state_snapshot()


@app.post("/start")
async def start_miner() -> dict:
    try:
        await controller.start()
    except RuntimeError as exc:  # pragma: no cover - FastAPI handles errors at runtime
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "starting"}


@app.post("/stop")
async def stop_miner() -> dict:
    await controller.stop()
    return {"status": "stopped"}


@app.post("/login")
async def submit_login(request: LoginRequest) -> dict:
    try:
        controller.submit_login(request.username, request.password, request.token or "")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "submitted"}


@app.post("/select-channel")
async def select_channel(selection: ChannelSelection) -> dict:
    try:
        controller.select_channel(selection.channel_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "updated"}


@app.get("/settings")
async def get_settings() -> dict:
    return controller.settings_snapshot()


@app.patch("/settings")
async def patch_settings(update: SettingsUpdate) -> dict:
    try:
        return controller.update_settings(update.dict(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid priority mode: {exc.args[0]}") from exc


@app.get("/status")
async def status() -> dict:
    return {"running": controller.is_running()}
