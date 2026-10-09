import hmac
import os
import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, Response
import json
from pydantic import BaseModel, Field

from app.api.routes.rooms import (
    cancel_empty_room_cleanup,
    connection_manager,
    game_orchestrator_service,
    room_repository,
)

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


def _room_or_404(room_id: str) -> dict:
    room = room_repository.get(room_id)
    if room is None:
        room = room_repository.get_archived(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="房间不存在")
    return room


def _player_name_map(room: dict) -> dict[str, str]:
    return {
        player.get("id"): player.get("name") or player.get("id")
        for player in room.get("players", [])
        if player.get("id")
    }


def _agent_audit_entries(room: dict) -> list[dict]:
    """Return one normalized row for every player question and AI answer."""
    entries = list(room.get("agent_audit_log", []) or [])
    names = _player_name_map(room)
    normalized = list(entries)
    existing_questions = Counter(
        (entry.get("player_id"), entry.get("question", ""))
        for entry in entries
    )
    response_questions = Counter()
    for event in room.get("event_history", []) or []:
        event_type = event.get("event_type")
        if event_type == "DM_RESPONSE":
            payload = event.get("payload", {}) or {}
            player_id = event.get("actor_player_id")
            question = payload.get("question", "")
            key = (player_id, question)
            if existing_questions[key] > 0:
                existing_questions[key] -= 1
                continue
            response_questions[key] += 1
            normalized.append({
                "id": event.get("id"),
                "created_at": event.get("created_at"),
                "player_id": player_id,
                "player_name": names.get(player_id, player_id),
                "question": question,
                "answer": payload.get("answer", ""),
                "visibility": payload.get("visibility", "private"),
                "clue_ids": payload.get("clue_ids", []),
                "tool_used": payload.get("tool_used", False),
                "tool_name": payload.get("tool_name"),
                "tool_status": payload.get("tool_status"),
                "tool_data": payload.get("tool_data", {}),
            })

    for event in room.get("event_history", []) or []:
        if event.get("event_type") != "PLAYER_MESSAGE":
            continue
        payload = event.get("payload", {}) or {}
        player_id = event.get("actor_player_id")
        question = payload.get("content", "")
        key = (player_id, question)
        if existing_questions[key] > 0:
            existing_questions[key] -= 1
            continue
        if response_questions[key] > 0:
            response_questions[key] -= 1
            continue
        normalized.append({
            "id": event.get("id"),
            "created_at": event.get("created_at"),
            "player_id": player_id,
            "player_name": names.get(player_id, player_id),
            "character_id": next(
                (
                    player.get("character_id")
                    for player in room.get("players", [])
                    if player.get("id") == player_id
                ),
                None,
            ),
            "question": question,
            "answer": "AI 未返回（请求可能失败或连接中断）",
            "visibility": "private",
            "clue_ids": [],
            "tool_used": False,
            "tool_name": None,
            "tool_status": "failed",
            "tool_data": {},
        })
    return normalized


def _room_summary(room: dict) -> dict:
    events = list(room.get("event_history", []))
    players = room.get("players", [])
    names = _player_name_map(room)
    event_counts = Counter(event.get("event_type") for event in events)
    votes = room.get("votes", {}) or {}
    ending = room.get("ending") or {}
    audit = _agent_audit_entries(room)
    tool_entries = [entry for entry in audit if entry.get("tool_used")]
    tool_statuses = Counter(entry.get("tool_status") or "unknown" for entry in tool_entries)
    player_stats = []
    for player in players:
        player_id = player.get("id")
        player_events = [event for event in events if event.get("actor_player_id") == player_id]
        player_stats.append({
            "player_id": player_id,
            "player_name": names.get(player_id, player_id),
            "character_id": player.get("character_id"),
            "is_host": bool(player.get("is_host")),
            "message_count": sum(event.get("event_type") == "PLAYER_MESSAGE" for event in player_events),
            "question_count": sum(entry.get("player_id") == player_id for entry in audit),
            "tool_call_count": sum(entry.get("player_id") == player_id and entry.get("tool_used") for entry in audit),
            "location_count": sum(event.get("event_type") == "LOCATION_ENTERED" for event in player_events),
            "inspection_count": sum(event.get("event_type") == "OBJECT_INSPECTED" for event in player_events),
            "clue_count": len(player.get("clue_ids", [])),
            "vote": votes.get(player_id),
            "has_voted": player_id in votes,
            "event_count": len(player_events),
        })

    stage_events = [event for event in events if event.get("event_type") == "STAGE_CHANGED"]
    vote_counts = Counter(votes.values())
    highest = max(vote_counts.values(), default=0)
    vote_leaders = [target for target, count in vote_counts.items() if count == highest]
    return {
        "room_id": room.get("id"),
        "script_id": room.get("script_id"),
        "script_version": room.get("script_version"),
        "status": room.get("status"),
        "created_at": room.get("created_at"),
        "player_count": len(players),
        "required_players": room.get("required_players", 0),
        "event_count": len(events),
        "event_counts": dict(event_counts),
        "stage_change_count": len(stage_events),
        "message_count": event_counts.get("PLAYER_MESSAGE", 0),
        "public_message_count": event_counts.get("PUBLIC_MESSAGE", 0),
        "clue_release_count": event_counts.get("CLUE_RELEASED", 0),
        "investigation_count": event_counts.get("LOCATION_ENTERED", 0) + event_counts.get("OBJECT_INSPECTED", 0),
        "vote_count": len(votes),
        "vote_distribution": dict(vote_counts),
        "vote_leaders": vote_leaders,
        "vote_tied": len(vote_leaders) > 1 and highest > 0,
        "ending": {
            "id": ending.get("id"),
            "title": ending.get("title"),
            "total_votes": ending.get("total_votes", len(votes)),
            "vote_counts": ending.get("vote_counts", dict(vote_counts)),
        } if ending else None,
        "ai": {
            "request_count": len(audit),
            "tool_call_count": len(tool_entries),
            "tool_status_counts": dict(tool_statuses),
            "clue_delivery_count": sum(len(entry.get("clue_ids", [])) for entry in audit),
            "failed_tool_count": sum(status not in {"completed", "success", "already_triggered"} for status in tool_statuses.elements()),
        },
        "players": player_stats,
    }


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
    active_ids = {room.get("id") for room in rooms}
    for archived_room in room_repository.list_archived():
        if archived_room.get("id") not in active_ids:
            rooms.append(archived_room)
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
            "end_reason": room.get("end_reason"),
            "archived": bool(room.get("end_reason")),
        }
        for room in rooms
    ]


@router.get("/rooms/{room_id}")
async def admin_room_detail(room_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    return _room_or_404(room_id)


@router.get("/rooms/{room_id}/summary")
async def admin_room_summary(room_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    room = _room_or_404(room_id)
    return _room_summary(room)


@router.get("/rooms/{room_id}/players/{player_id}/history")
async def admin_player_history(
    room_id: str,
    player_id: str,
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization)
    room = _room_or_404(room_id)
    player = next(
        (item for item in room.get("players", []) if item.get("id") == player_id),
        None,
    )
    if player is None:
        raise HTTPException(status_code=404, detail="玩家不存在")
    events = [
        event for event in room.get("event_history", [])
        if event.get("actor_player_id") == player_id
        or event.get("target_player_id") == player_id
    ]
    audit = [
        entry for entry in _agent_audit_entries(room)
        if entry.get("player_id") == player_id
    ]
    return {
        "room_id": room_id,
        "player": player,
        "events": events,
        "agent_audit": audit,
    }


@router.get("/rooms/{room_id}/export")
async def export_admin_room(room_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    room = _room_or_404(room_id)
    audit_entries = _agent_audit_entries(room)
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "room": room,
        "summary": _room_summary(room),
        "events": room.get("event_history", []),
        "agent_audit": audit_entries,
        "peer_reviews": room.get("peer_reviews", {}),
    }
    filename = f"room-{room_id}-admin-export.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/rooms/{room_id}")
async def delete_admin_room(room_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    room = _room_or_404(room_id)
    cancel_empty_room_cleanup(room_id)
    game_orchestrator_service.stop(room_id)
    connection_manager.remove_room(room_id)
    if room.get("end_reason"):
        room_repository.delete_archived(room_id)
    else:
        room_repository.destroy(room_id)
    return {
        "deleted": True,
        "room_id": room_id,
        "script_id": room.get("script_id"),
    }


@router.get("/rooms/{room_id}/agent-audit")
async def admin_agent_audit(room_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    room = _room_or_404(room_id)
    return {
        "room_id": room_id,
        "entries": _agent_audit_entries(room),
        "peer_reviews": room.get("peer_reviews", {}),
    }
