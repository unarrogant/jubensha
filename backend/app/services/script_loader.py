import json
import re
from pathlib import Path


PROJECT_ROOT=Path(__file__).resolve().parents[3]
CONTENT_ROOT=PROJECT_ROOT/"content"


class ScriptLoader:
    def __init__(self,content_root:Path=CONTENT_ROOT):
        self.content_root=content_root

    def list_scripts(self)->list[dict]:
        scripts=[]

        if not self.content_root.exists():
            return scripts
        for script_dir in self.content_root.iterdir():
            if not script_dir.is_dir():
                continue
            try:
                manifest=self.load_manifest(script_dir.name)
                scripts.append(manifest)
            except (FileNotFoundError,ValueError,json.JSONDecodeError):
                continue

        return scripts

    def load_manifest(
            self,
            script_id:str,
            version:int | None=None
    )->dict:
        script_dir=self.content_root/script_id

        if not script_dir.is_dir():
            raise FileNotFoundError(f"剧本不存在：{script_id}")
        if version is None:
            version=self._find_latest_version(script_dir)

        manifest_path = script_dir / f"v{version}" / "manifest.json"

        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"剧本版本不存在：{script_id} v{version}"
            )

        with manifest_path.open("r", encoding="utf-8") as file:
            manifest = json.load(file)

        return manifest

    @staticmethod
    def _find_latest_version(script_dir: Path) -> int:
        versions = []

        for child in script_dir.iterdir():
            if not child.is_dir():
                continue

            match = re.fullmatch(r"v([1-9][0-9]*)", child.name)

            if match:
                versions.append(int(match.group(1)))

        if not versions:
            raise FileNotFoundError(
                f"剧本没有可用版本：{script_dir.name}"
            )

        return max(versions)