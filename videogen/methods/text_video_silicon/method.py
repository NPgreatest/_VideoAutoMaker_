from __future__ import annotations
import time
from pathlib import Path
from typing import Dict, Any

from videogen.methods.base import BaseMethod
from videogen.methods.registry import register_method
from videogen.methods.text_video_silicon.constants import (
    SILICONFLOW_API_TOKEN, TEXT_TO_VIDEO_MODEL, DB_PATH, STATUS_SUBMITTED
)
from .sf_api import submit_video
from .store import TaskCSV
from .worker import start_background_worker


@register_method
class TextVideoSilicon(BaseMethod):
    NAME = "text_video"
    OUTPUT_KIND = "video"

    def __init__(self) -> None:
        super().__init__()
        self._stores = {}

    def _get_store(self, workdir: Path) -> TaskCSV:
        key = "global_db"
        if key not in self._stores:
            db_path = Path(DB_PATH).resolve()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            store = TaskCSV(db_path)
            self._stores[key] = store
            start_background_worker(store)
        return self._stores[key]

    def run(
        self,
        *,
        prompt: str,
        project: str,
        target_name: str,
        text: str,
        workdir: Path,
        duration_ms: int | None = None,
    ) -> Dict[str, Any]:
        if not SILICONFLOW_API_TOKEN:
            return {
                "ok": False,
                "artifacts": [],
                "meta": {},
                "error": "Missing SILICONFLOW_API_TOKEN.",
            }

        # 提交任务
        request_id = submit_video(prompt)
        if not request_id:
            return {
                "ok": False,
                "artifacts": [],
                "meta": {},
                "error": "Submit failed (no requestId).",
            }

        # 存入全局 CSV
        store = self._get_store(workdir)
        now = time.time()
        row = {
            "request_id": request_id,
            "project": project,
            "target_name": target_name,
            "prompt": prompt,
            "model": TEXT_TO_VIDEO_MODEL,
            "status": STATUS_SUBMITTED,
            "output_path": "",
            "source_url": "",
            "created_ts": str(now),
            "updated_ts": str(now),
            "error": "",
            "poll_count": "0",
            "workdir": str(workdir.resolve()),
        }
        store.upsert(row)

        db_path = Path(DB_PATH).resolve()
        return {
            "ok": True,
            "artifacts": [],
            "meta": {
                "request_id": request_id,
                "project": project,
                "target_name": target_name,
                "status": STATUS_SUBMITTED,
                "output_path": str(
                    workdir / "project" / project / f"{target_name}.mp4"
                ),
                "db_path": str(db_path),
            },
            "error": None,
        }
