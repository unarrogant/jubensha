import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.rooms import room_repository

router = APIRouter()
_sessions: dict[str, datetime] = {}
SESSION_TTL = timedelta(hours=8)


class AdminLogin(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _require_admin(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要管理员登录")

    token = authorization[7:].strip()
    expires_at = _sessions.get(token)
    if not expires_at or expires_at <= datetime.now(timezone.utc):
        _sessions.pop(token, None)
        raise HTTPException(status_code=401, detail="管理员登录已过期")


@router.post("/login")
async def admin_login(data: AdminLogin):
    expected_username = os.getenv("ADMIN_USERNAME", "admin")
    expected_password = os.getenv("ADMIN_PASSWORD", "")
    if not expected_password:
        raise HTTPException(status_code=503, detail="后端未配置 ADMIN_PASSWORD")

    if not hmac.compare_digest(data.username, expected_username) or not hmac.compare_digest(
        data.password, expected_password
    ):
        raise HTTPException(status_code=401, detail="管理员账号或密码错误")

    token = secrets.token_urlsafe(32)
    _sessions[token] = datetime.now(timezone.utc) + SESSION_TTL
    return {"access_token": token, "expires_in": int(SESSION_TTL.total_seconds())}


@router.get("/rooms")
async def admin_rooms(authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    rooms = room_repository._list_rooms()
    return [
        {
            "id": room["id"],
            "script_id": room.get("script_id"),
            "script_version": room.get("script_version"),
            "status": room.get("status"),
            "player_count": room.get("player_count", 0),
            "required_players": room.get("required_players", 0),
            "stage_id": room.get("game", {}).get("stage_id"),
            "created_at": room.get("created_at"),
            "updated_at": room.get("game", {}).get("stage_started_at"),
        }
        for room in rooms
    ]


@router.get("/rooms/{room_id}")
async def admin_room_detail(room_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    room = room_repository.get(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="房间不存在")
    return room
