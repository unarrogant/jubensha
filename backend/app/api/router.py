from fastapi import APIRouter

from app.api.routes.scripts import router as scripts_router
from app.api.routes.rooms import router as rooms_router
from app.api.routes.ws import router as ws_router
from app.api.routes.admin import router as admin_router

api_router=APIRouter()

api_router.include_router(
    rooms_router,
    prefix="/rooms",
    tags=["房间"]
)

api_router.include_router(
    scripts_router,
    prefix="/scripts",
    tags=["剧本"]
)

api_router.include_router(
    ws_router,
    prefix="/rooms",
    tags=["实时连接"],
)

api_router.include_router(
    admin_router,
    prefix="/admin",
    tags=["管理员"],
)
