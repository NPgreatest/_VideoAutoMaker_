from __future__ import annotations

import os.path
import time
from pathlib import Path
from typing import Dict, Any, Optional

from videogen.methods.base import BaseMethod
from videogen.methods.registry import register_method
from videogen.methods.text_video_silicon.constants import (
    SILICONFLOW_API_TOKEN, TEXT_TO_VIDEO_MODEL, DB_PATH, STATUS_SUBMITTED
)
from .sf_api import submit_video
from .store import TaskCSV
from .worker import start_background_worker
from ...llm_engine import get_engine
from ...pipeline.schema import ScriptBlock


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
        block: Optional[ScriptBlock] = None
    ) -> Dict[str, Any]:
        if not SILICONFLOW_API_TOKEN:
            return {"ok": False, "artifacts": [], "meta": {}, "error": "Missing SILICONFLOW_API_TOKEN."}

        # 提交任务
        if block and block.generation and block.generation.ok and 'request_id' in block.generation.meta and os.path.exists(block.generation.meta['output_path']):
            request_id = block.generation.meta['request_id']
        else:
            request_id = submit_video(prompt)
        if not request_id:
            return {"ok": False, "artifacts": [], "meta": {}, "error": "Submit failed (no requestId)."}

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
            "duration": str(duration_ms / 1000 if duration_ms else 5.0),
        }
        store.upsert(row)

        # Always wait for completion for text_video_silicon method
        print(f"⏳ Waiting for video generation to complete for {target_name}...")
        completed_task = store.wait_for_completion(request_id, timeout_seconds=300)
        
        if completed_task:
            status = completed_task.get("status", "")
            output_path = completed_task.get("output_path", "")
            error = completed_task.get("error", "")
            
            if status == "succeed" and output_path and os.path.exists(output_path):
                return {
                    "ok": True,
                    "artifacts": [output_path],
                    "meta": {
                        "request_id": request_id,
                        "project": project,
                        "target_name": target_name,
                        "status": status,
                        "output_path": output_path,
                        "source_url": completed_task.get("source_url", ""),
                    },
                    "error": None,
                }
            else:
                return {
                    "ok": False,
                    "artifacts": [],
                    "meta": {
                        "request_id": request_id,
                        "project": project,
                        "target_name": target_name,
                        "status": status,
                        "output_path": output_path,
                    },
                    "error": error or f"Task failed with status: {status}",
                }
        else:
            return {
                "ok": False,
                "artifacts": [],
                "meta": {
                    "request_id": request_id,
                    "project": project,
                    "target_name": target_name,
                    "status": "timeout",
                    "output_path": "",
                },
                "error": f"Timeout waiting for task completion (300s)",
            }

    def generate_prompt(self, text: str) -> str:
        """
        Convert a line of dialogue into a vivid cinematic scene prompt for text-to-video models (e.g. Sora, Runway).
        Uses an English few-shot example to demonstrate desired style and structure.
        """
        engine = get_engine()

        system_prompt = (
            "You are an expert cinematic visual director who converts dialogue lines "
            "into vivid scene descriptions for text-to-video generation models like Sora or Runway.\n"
            "Focus only on what the camera would show: the environment, lighting, motion, and atmosphere.\n"
            "Do not describe sound, dialogue, or voice-over. Your output must feel cinematic and visual.\n\n"
            "=== EXAMPLE ===\n\n"
            "Input line:\n"
            "\"This is the moment when the meteor struck the Earth.\"\n\n"
            "Output:\n"
            "A blazing meteor streaks through the night sky, leaving a trail of fire and smoke. "
            "The camera follows it in slow motion as it descends toward a vast desert landscape. "
            "Upon impact, a shockwave of light and dust erupts into the air, illuminating the horizon in orange and white. "
            "=== END OF EXAMPLE ===\n"
            "Now generate a similar cinematic description for the following line."
        )

        user_prompt = (
            f"Input line:\n{text.strip()}\n\n"
            "Output:"
        )

        res = engine.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=400,
        )

        content = res["content"].strip()


        prompt = "\n".join(
            l for l in content.splitlines() if not l.strip().lower().startswith("title:")
        ).strip()

        return prompt
