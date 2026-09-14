from fastapi import APIRouter,HTTPException

from app.services.script_loader import ScriptLoader

router=APIRouter()
script_loader=ScriptLoader()

@router.get("")
async def list_scripts():
    """获取所有剧本的当前最高版本信息"""
    return script_loader.list_scripts()

@router.get("/{script_id}")
async def get_script(script_id:str,version:int|None=None):
    """获取某个剧本的manifest信息"""
    try:
        return script_loader.load_manifest(
            script_id,
            version,
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
        )from error
    