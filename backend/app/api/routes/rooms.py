import asyncio

from fastapi import APIRouter,HTTPException

from app.repositories.room_repository import RoomRepository
from app.schemas.room import RoomCreate,RoomCreateResponse,RoomListItem,RoomPublic,RoomStart,RoomExit,RoomExitResponse
from app.schemas.players import PlayerJoin,PlayerJoinResponse,PlayerListItem,CharacterPrivate
from app.services.role_service import RoleService
from app.services.script_bundle import ScriptBundleLoader
from app.services.game_service import GameService
from app.schemas.game import GameStatePublic,VoteCreate,VoteResponse,VoteStatus
from app.schemas.investigation import EnterLocationRequest,InspectObjectRequest,InvestigationMessage
from app.services.investigation_service import InvestigationService
from app.schemas.clue import CluePublic
from app.schemas.message import  PlayerPrivateMessageCreate,PlayerPrivateMessagePublic
from app.schemas.dm import DMMessagePublic
from app.services.message_service import MessageService
from app.services.dm_service import DMService
from app.realtime.connection_manager import connection_manager
from app.services.dm_agent_service import DMAgentService
from app.services.game_orchestrator_service import GameOrchestratorService
from app.services.reasoning_service import ReasoningService

router=APIRouter()
room_repository=RoomRepository()
bundle_loader=ScriptBundleLoader()
role_service=RoleService(
    room_repository=room_repository,
    bundle_loader=bundle_loader,
)
game_service=GameService(
    room_repository=room_repository,
    bundle_loader=bundle_loader
)
investigation_service=InvestigationService(
    room_repository=room_repository,
    bundle_loader=bundle_loader
)
message_service=MessageService(
    room_repository=room_repository,
    bundle_loader=bundle_loader
)
dm_service=DMService(
    room_repository=room_repository,
)
reasoning_service = ReasoningService(
    room_repository=room_repository,
    bundle_loader=bundle_loader,
)
dm_agent_service = DMAgentService(
    room_repository=room_repository,
    bundle_loader=bundle_loader,
    investigation_service=investigation_service,
    reasoning_service=reasoning_service,
)
game_orchestrator_service = GameOrchestratorService(
    room_repository=room_repository,
    bundle_loader=bundle_loader,
    game_service=game_service,
    dm_agent_service=dm_agent_service,
    dm_service=dm_service,
    connection_manager=connection_manager,
)

EMPTY_ROOM_GRACE_SECONDS = 60
_empty_room_cleanup_tasks: dict[str, asyncio.Task] = {}


def cancel_empty_room_cleanup(room_id: str) -> None:
    task = _empty_room_cleanup_tasks.pop(room_id, None)
    if task and not task.done():
        task.cancel()


def schedule_empty_room_cleanup(room_id: str) -> None:
    cancel_empty_room_cleanup(room_id)

    async def cleanup() -> None:
        current_task = asyncio.current_task()
        try:
            await asyncio.sleep(EMPTY_ROOM_GRACE_SECONDS)

            # 宽限期内有人重连，保留房间和原有 thread/state。
            if connection_manager.get_player_ids(room_id):
                return

            room = room_repository.get(room_id)
            if room is None:
                return

            game_orchestrator_service.stop(room_id)
            connection_manager.remove_room(room_id)
            room_repository.destroy(room_id)
        except asyncio.CancelledError:
            return
        finally:
            if _empty_room_cleanup_tasks.get(room_id) is current_task:
                _empty_room_cleanup_tasks.pop(room_id, None)

    _empty_room_cleanup_tasks[room_id] = asyncio.create_task(
        cleanup(),
        name=f"empty-room-cleanup:{room_id}",
    )

def get_character(
        characters:list[dict],
        character_id:str|None,
)->dict|None:
    if character_id is None:
        return None

    for character in characters:
        if character.get("id")==character_id:
            return character

    return None


def get_character_name(
        characters:list[dict],
        character_id:str|None,
)->str|None:
    character=get_character(characters, character_id)
    return character.get("name") if character else None

def build_room_public(room:dict)->dict:
    return {
        "id":room["id"],
        "script_id":room["script_id"],
        "script_version":room["script_version"],
        "status":room["status"],
        "required_players":room["required_players"],
        "player_count":room["player_count"],
        "dm_status":room.get("dm_status", "ready"),
    }

def build_player_list(room:dict)->list[dict]:
    bundle=bundle_loader.load(
        room["script_id"],
        room["script_version"],
    )
    characters=bundle["characters"]
    result=[]

    for player in room["players"]:
        character=get_character(
            characters,
            player.get("character_id"),
        )
        result.append({
            "name":player["name"],
            "character_name":character.get("name") if character else None,
            "character_avatar":character.get("avatar") if character else None,
        })

    return result

async def broadcast_lobby(room:dict, event_type:str="LOBBY_UPDATED")->None:
    await connection_manager.broadcast_room(
        room_id=room["id"],
        event={
            "type":event_type,
            "room":build_room_public(room),
            "players":build_player_list(room),
        },
    )

async def push_private_message(
        room_id:str,
        player_id:str,
        content:str,
        clue_ids: list[str] | None = None,
)->dict:
    message=dm_service.send_private(
        room_id=room_id,
        player_id=player_id,
        content=content,
        clue_ids=clue_ids,
    )

    await connection_manager.send_to_player(
        room_id=room_id,
        player_id=player_id,
        event={
            "type":"PRIVATE_MESSAGE",
            "message":message,
        },
    )

    return message

async def push_public_message(
    room_id: str,
    content: str,
) -> dict:
    message = dm_service.send_public(
        room_id=room_id,
        content=content,
    )

    await connection_manager.broadcast_room(
        room_id=room_id,
        event={
            "type": "PUBLIC_MESSAGE",
            "message": message,
        },
    )

    return message


@router.post(
    "",
    response_model=RoomCreateResponse,
    status_code=201,
)
async def create_room(data:RoomCreate):
    try:
        return room_repository.create(
            script_id=data.script_id,
            host_name=data.host_name
        )

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        )from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

@router.get(
    "",
    response_model=list[RoomListItem],
)
async def list_waiting_rooms():
    result=[]

    for room in room_repository.list_waiting():
        host=next(
            (
                player
                for player in room["players"]
                if player["id"] == room["host_player_id"]
            ),
            None,
        )
        result.append({
            **build_room_public(room),
            "host_name":host["name"] if host else "未知房主",
            "created_at":room["created_at"],
        })

    return result

@router.get(
    "/{room_id}",
    response_model=RoomPublic,
)
async def get_room(room_id:str):
    room=room_repository.get(room_id)

    if room is None:
        raise HTTPException(
            status_code=404,
            detail="房间不存在"
        )

    return room

@router.post(
    "/{room_id}/join",
    response_model=PlayerJoinResponse,
    status_code=201
)

async def join_room(
    room_id:str,
    data:PlayerJoin,
):
    try:
        player=room_repository.join(
            room_id=room_id,
            name=data.name
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )from error
    if player is None:
        raise HTTPException(
            status_code=404,
            detail="房间不存在",

        )

    room=room_repository.get(room_id)
    await broadcast_lobby(room)
    return player

@router.get(
    "/{room_id}/players",
    response_model=list[PlayerListItem],
)
async def list_room_players(room_id:str):
    room=room_repository.get(room_id)

    if room is None:
        raise HTTPException(
            status_code=404,
            detail="房间不存在",
        )

    
    return build_player_list(room)

    

@router.post(
    "/{room_id}/start",
    response_model=RoomPublic,
)
async def start_room(
    room_id:str,
    data:RoomStart,
):
    room=room_repository.get(room_id)

    if room is None:
        raise HTTPException(
            status_code=404,
            detail="房间不存在",
        )

    if room["host_player_id"]!=data.host_player_id:
        raise HTTPException(
            status_code=403,
            detail="只有房主可以开始游戏",

        )

    if room["player_count"] != room["required_players"]:
        raise HTTPException(
            status_code=400,
            detail=f"需要正好{room['required_players']}名玩家才能开始",
        )

    try:
        role_service.assign_roles(room_id)
        game_service.initialize(room_id)
        started_room=room_repository.start(room_id)
        await broadcast_lobby(started_room, "GAME_STARTED")
        game_orchestrator_service.start(started_room["id"])
        return started_room

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        )from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )from error

@router.post(
    "/{room_id}/exit",
    response_model=RoomExitResponse,
)
async def exit_room(room_id: str, data: RoomExit):
    room = room_repository.get(room_id)

    if room is None:
        raise HTTPException(status_code=404, detail="房间不存在")

    if room.get("status") != "ended":
        raise HTTPException(
            status_code=400,
            detail="游戏结束后才能退出房间",
        )

    try:
        result = room_repository.mark_player_exited(
            room_id=room_id,
            player_id=data.player_id,
        )
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(
            status_code=404 if isinstance(error, FileNotFoundError) else 400,
            detail=str(error),
        ) from error

    if result["destroyed"]:
        cancel_empty_room_cleanup(room_id)
        game_orchestrator_service.stop(room_id)
        connection_manager.remove_room(room_id)
        room_repository.destroy(room_id)

    return result

@router.get(
    "/{room_id}/players/{player_id}/character",
    response_model=CharacterPrivate
)
async def get_my_character(
    room_id:str,
    player_id:str,
):
    room=room_repository.get(room_id)

    if room is None:
        raise HTTPException(
            status_code=404,
            detail="房间不存在"
        )

    player=None

    for item in room["players"]:
        if item["id"]==player_id:
            player=item
            break

    if player is None:
        raise HTTPException(
            status_code=404,
            detail="玩家不在这个房间中"
        )

    if room["status"] not in {"playing", "ended"}:
        raise HTTPException(
            status_code=400,
            detail="游戏尚未开始",
        )

    character_id=player.get("character_id")

    if character_id is None:
        raise HTTPException(
            status_code=404,
            detail="角色尚未分配"
        )

    bundle=bundle_loader.load(
        room["script_id"],
        room["script_version"],
    )

    for character in bundle["characters"]:
        if character.get("id")==character_id:
            return character

    raise HTTPException(
        status_code=404,
        detail="角色资料不存在",
    )

@router.get(
    "/{room_id}/state",
    response_model=GameStatePublic,
)
async def get_game_state(room_id:str):
    room=room_repository.get(room_id)

    if room is None:
        raise HTTPException(
            status_code=404,
            detail="房间不存在",
        )

    try:
        return game_service.get_public_state(room_id)
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.get(
    "/{room_id}/vote",
    response_model=VoteStatus,
)
async def get_vote_status(room_id:str, player_id:str):
    try:
        return game_service.get_vote_status(
            room_id=room_id,
            player_id=player_id,
        )
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.post(
    "/{room_id}/vote",
    response_model=VoteResponse,
)
async def cast_vote(room_id:str, data:VoteCreate):
    try:
        result = game_service.cast_vote(
            room_id=room_id,
            player_id=data.player_id,
            suspect_id=data.suspect_id,
        )
        await connection_manager.broadcast_room(
            room_id=room_id,
            event={
                "type":"VOTE_UPDATED",
                "vote_count":result["vote_count"],
                "required_votes":result["required_votes"],
            },
        )
        return result
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.post(
    "/{room_id}/investigation/enter",
    response_model=InvestigationMessage,
)
async def enter_location(
    room_id:str,
    data:EnterLocationRequest,
):
    try:
        result=investigation_service.enter_location(
            room_id=room_id,
            player_id=data.player_id,
            location_id=data.location_id
        )

        await push_private_message(
            room_id=room_id,
            player_id=data.player_id,
            content=result["message"],
        )

        return result
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        )from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )from error

@router.post(
    "/{room_id}/investigation/inspect",
    response_model=InvestigationMessage,
)
async def inspect_object(
    room_id:str,
    data:InspectObjectRequest,
):
    try:
        result=investigation_service.inspect_object(
            room_id=room_id,
            player_id=data.player_id,
            location_id=data.location_id,
            object_text=data.object_text,
        )

        await push_private_message(
            room_id=room_id,
            player_id=data.player_id,
            content=result["message"],
            clue_ids=(
                [result["clue_id"]]
                if result.get("clue_id")
                else []
            ),
        )

        return result
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

@router.get(
    "/{room_id}/players/{player_id}/clues",
    response_model=list[CluePublic],
)
async def list_my_clues(
    room_id:str,
    player_id:str,
):
    room=room_repository.get(room_id)

    if room is None:
        raise HTTPException(
            status_code=404,
            detail="房间不存在",
        )

    player=None

    for item in room["players"]:
        if item["id"]==player_id:
            player=item
            break

    if player is None:
        raise HTTPException(
            status_code=404,
            detail="玩家不在这个房间中",
        )

    bundle = bundle_loader.load(
        room["script_id"],
        room["script_version"],
    )

    clue_ids=player.get("clue_ids",[])
    result=[]

    for clue in bundle["clues"]:
        if clue.get("id") in clue_ids:
            result.append(clue)

    return result

@router.post(
    "/{room_id}/messages",
    response_model=PlayerPrivateMessagePublic,
    status_code=201,
)
async def send_message(
    room_id:str,
    data: PlayerPrivateMessageCreate,
):
    try:
        return message_service.send_player_message(
            room_id=room_id,
            player_id=data.player_id,
            content=data.content,
        )
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error
@router.get(
    "/{room_id}/messages",
    response_model=list[
        PlayerPrivateMessagePublic | DMMessagePublic
    ],
)
async def list_messages(room_id:str,player_id:str):
    try:
        return message_service.list_messages(
            room_id=room_id,
            player_id=player_id,
        )
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

