"""脚本存储模块：多脚本的创建、删除、重命名、保存与加载。

脚本以 JSON 文件形式保存在 scripts/ 目录下，每个脚本一个文件。
文件名使用脚本名的安全化形式 + 短ID，避免重名和非法字符问题。
"""

import json
import os
import re
import uuid
from datetime import datetime
from typing import Optional

from event_types import RecordedEvent

SCRIPTS_DIR_NAME = "scripts"


def _safe_filename(name: str) -> str:
    """把脚本名转换为安全的文件名。"""
    safe = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    return safe[:50] or "script"


class Script:
    """一个录制脚本（内存中的表示）。"""

    def __init__(
        self,
        name: str,
        events: Optional[list[RecordedEvent]] = None,
        file_id: Optional[str] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ):
        self.name = name
        self.events = events or []
        self.file_id = file_id or uuid.uuid4().hex[:8]
        now = datetime.now().isoformat(timespec="seconds")
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "file_id": self.file_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "event_count": len(self.events),
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Script":
        events = [RecordedEvent.from_dict(e) for e in d.get("events", [])]
        return cls(
            name=d.get("name", "未命名"),
            events=events,
            file_id=d.get("file_id"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )


class ScriptStorage:
    """脚本的持久化管理。"""

    def __init__(self, base_dir: str):
        self.scripts_dir = os.path.join(base_dir, SCRIPTS_DIR_NAME)
        os.makedirs(self.scripts_dir, exist_ok=True)

    # ---------- 路径辅助 ----------

    def _path(self, script: Script) -> str:
        return os.path.join(self.scripts_dir, f"{_safe_filename(script.name)}_{script.file_id}.json")

    # ---------- CRUD ----------

    def save(self, script: Script) -> str:
        """保存脚本，返回文件路径。"""
        script.updated_at = datetime.now().isoformat(timespec="seconds")
        path = self._path(script)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(script.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    def delete(self, script: Script) -> bool:
        """删除脚本文件。"""
        path = self._path(script)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def load_all(self) -> list[Script]:
        """加载全部脚本。"""
        scripts = []
        if not os.path.isdir(self.scripts_dir):
            return scripts
        for fn in os.listdir(self.scripts_dir):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(self.scripts_dir, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                scripts.append(Script.from_dict(data))
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        # 按更新时间倒序
        scripts.sort(key=lambda s: s.updated_at, reverse=True)
        return scripts

    # ---------- 导出 ----------

    def export_json(self, script: Script, export_path: str) -> str:
        """把脚本导出到指定路径。"""
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(script.to_dict(), f, ensure_ascii=False, indent=2)
        return export_path
