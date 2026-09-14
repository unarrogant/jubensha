import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.routes.rooms import (
    build_player_list,
    build_room_public,
    cancel_empty_room_cleanup,
    dm_agent_service,
    message_service,
    push_private_message,
    push_public_message,
    room_repository,
    schedule_empty_room_cleanup,
)
from app.realtime.connection_manager import connection_manager
from app.schemas.message import PlayerPrivateMessageCreate

router=APIRouter()
logger=logging.getLogger(__name__)

@router.websocket("/{room_id}/ws")
async def room_websocket(
    websocket:WebSocket,
    room_id:str,
    player_id:str
):
    room=room_repository.get(room_id)

    if room is None:
        await websocket.close(code=1008)
        return

    player=None

    for item in room.get("players",[]):
        if item.get("id")==player_id:
            player=item
            break

    if player is None:
        await websocket.close(code=1008)
        return

    await connection_manager.connect(
        room_id,
        player_id,
        websocket,
    )
    cancel_empty_room_cleanup(room_id)

    try:
        await websocket.send_json({
            "type": "CONNECTED",
            "room_id": room_id,
            "player_id": player_id,
        })

        await websocket.send_json({
            "type":"LOBBY_UPDATED",
            "room":build_room_public(room),
            "players":build_player_list(room),
        })

        public_messages = room.get(
            "messages",
            [],
        )

        private_messages = player.get(
            "private_messages",
            [],
        )

        history = sorted(
            [
                *public_messages,
                *private_messages,
            ],
            key=lambda message: message.get(
                "created_at",
                "",
            ),
        )

        await websocket.send_json({
            "type": "CHAT_HISTORY",
            "messages": history,
        })

        connected_player_ids = [
            item
            for item in connection_manager.get_player_ids(room_id)
            if item != player_id
        ]

        await websocket.send_json({
            "type": "VOICE_PEERS",
            "player_ids": connected_player_ids,
            "players": [
                {
                    "id": connected_player["id"],
                    "name": connected_player["name"],
                    "muted": connected_player.get("voice_muted", True),
                }
                for connected_player in room.get("players", [])
                if connected_player["id"] in connected_player_ids
            ],
        })

        player["voice_muted"] = True
        room_repository.save(room_id)
        await connection_manager.broadcast_room(
            room_id=room_id,
            event={
                "type": "VOICE_PEER_JOINED",
                "player_id": player_id,
                "player_name": player["name"],
                "muted": True,
            },
            exclude_player_id=player_id,
        )

        while True:
            data=await websocket.receive_json()

            if data.get("type") == "PING":
                await websocket.send_json({
                    "type": "PONG",
                })
            elif data.get("type") == "VOICE_STATE":
                muted = data.get("muted")

                if not isinstance(muted, bool):
                    await websocket.send_json({
                        "type": "ERROR",
                        "message": "语音状态缺少 muted 布尔值",
                    })
                    continue

                player["voice_muted"] = muted
                room_repository.save(room_id)
                await connection_manager.broadcast_room(
                    room_id=room_id,
                    event={
                        "type": "VOICE_STATE_CHANGED",
                        "player_id": player_id,
                        "player_name": player["name"],
                        "muted": muted,
                    },
                )
            elif data.get("type") in {
                "WEBRTC_OFFER",
                "WEBRTC_ANSWER",
                "WEBRTC_ICE_CANDIDATE",
            }:
                target_player_id = data.get("target_player_id")

                if not target_player_id or target_player_id == player_id:
                    await websocket.send_json({
                        "type": "ERROR",
                        "message": "WebRTC 信令缺少有效目标玩家",
                    })
                    continue

                target_exists = any(
                    item.get("id") == target_player_id
                    for item in room.get("players", [])
                )

                if not target_exists:
                    await websocket.send_json({
                        "type": "ERROR",
                        "message": "目标玩家不在房间内",
                    })
                    continue

                await connection_manager.send_to_player(
                    room_id=room_id,
                    player_id=target_player_id,
                    event={
                        "type": data["type"],
                        "from_player_id": player_id,
                        "offer": data.get("offer"),
                        "answer": data.get("answer"),
                        "candidate": data.get("candidate"),
                    },
                )
            elif data.get("type")=="PLAYER_PRIVATE_MESSAGE":
                try:
                    message_data=PlayerPrivateMessageCreate(
                        player_id=player_id,
                        content=data.get("content",""),
                    )

                    player_message=message_service.send_player_message(
                        room_id=room_id,
                        player_id=message_data.player_id,
                        content=message_data.content,
                    )
                    await connection_manager.send_to_player(
                        room_id=room_id,
                        player_id=player_id,
                        event={
                            "type": "CHAT_MESSAGE",
                            "message": player_message,
                        },
                    )

                    agent_result = await run_in_threadpool(
                        dm_agent_service.handle_player_message,
                        room_id=room_id,
                        player_id=player_id,
                        content=message_data.content,
                    )

                   
                    await push_private_message(
                        room_id=room_id,
                        player_id=player_id,
                        content=agent_result.content,
                        clue_ids=agent_result.clue_ids,
                    )
                    

                except ValidationError:
                    await websocket.send_json({
                        "type": "ERROR",
                        "message": "消息内容不能为空，且不能超过 1000 个字符",
                    })
                    continue

                except (FileNotFoundError, ValueError) as error:
                    await websocket.send_json({
                        "type": "ERROR",
                        "message": str(error),
                    })
                    continue

                except Exception:
                    logger.exception(
                        "DM failed to answer player %s in room %s",
                        player_id,
                        room_id,
                    )
                    await websocket.send_json({
                        "type": "ERROR",
                        "message": "主持人暂时无法回应，请稍后重试。",
                    })
                    continue

                

            else:
                await websocket.send_json({
                    "type": "ERROR",
                    "message": "不支持的消息类型",
                })

    except WebSocketDisconnect:
        pass

    finally:
        player_disconnected = connection_manager.disconnect(
            room_id,
            player_id,
            websocket,
        )

        if player_disconnected:
            player["voice_muted"] = True
            room_repository.save(room_id)
            await connection_manager.broadcast_room(
                room_id=room_id,
                event={
                    "type": "VOICE_PEER_LEFT",
                    "player_id": player_id,
                    "player_name": player["name"],
                },
                exclude_player_id=player_id,
            )

        if not connection_manager.get_player_ids(room_id):
            schedule_empty_room_cleanup(room_id)
