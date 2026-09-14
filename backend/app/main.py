from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.api.router import api_router
from app.services.script_loader import CONTENT_ROOT

app=FastAPI(
    title="剧本杀管理系统",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    api_router,
    prefix="/api"
)

@app.get("/api/health")
async def health():
    return {
        "status":"ok",
        "message":"剧本杀后端运行正常",
    }

app.mount(
    "/content",
    StaticFiles(directory=CONTENT_ROOT),
    name="content",
)

# 复用项目根目录 public/img 中已有的角色、主持人和线索卡图片。
PUBLIC_IMAGE_ROOT = Path(__file__).resolve().parents[2] / "public" / "img"
if PUBLIC_IMAGE_ROOT.is_dir():
    app.mount(
        "/img",
        StaticFiles(directory=PUBLIC_IMAGE_ROOT),
        name="public-images",
    )
