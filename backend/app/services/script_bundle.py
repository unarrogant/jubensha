import json
from pathlib import Path

from app.services.script_loader import CONTENT_ROOT,ScriptLoader

SCRIPT_FILES={
    "characters":"characters.json",
    "stages":"stages.json",
    "locations":"locations.json",
    "clues":"clues.json",
    "unlock_rules":"unlock_rules.json",
    "endings":"endings.json",
}

class ScriptBundleLoader:
    def __init__(self,content_root:Path=CONTENT_ROOT):
        self.content_root=content_root
        self.script_loader=ScriptLoader(content_root)

    def load(
            self,
            script_id:str,
            version:int|None=None,
    )->dict:
        manifest=self.script_loader.load_manifest(
            script_id,
            version,
        )

        actual_version=manifest["version"]

        version_dir=(self.content_root/script_id/f"v{actual_version}")

        bundle={"manifest":manifest}

        for key,filename in SCRIPT_FILES.items():
            file_path=version_dir/filename
            bundle[key]=self._load_json(file_path)

        dm_prompt_path=version_dir/"prompts"/"dm_system.md"

        if not dm_prompt_path.is_file():
            raise FileNotFoundError(
                f"缺少主持人提示词：{dm_prompt_path}"
            )

        bundle["dm_system"]=dm_prompt_path.read_text(
            encoding="utf-8"
        )

        return bundle

    @staticmethod
    def _load_json(file_path:Path)->dict|list:
        if not file_path.is_file():
            raise FileNotFoundError(
                f"缺少剧本文件：{file_path}"

            )

        with file_path.open("r",encoding="utf8") as file:
            return json.load(file)

        