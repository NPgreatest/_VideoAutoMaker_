from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional
import requests

from .constants import (
    SILICONFLOW_API_TOKEN, TEXT_TO_VIDEO_MODEL,
    SILICONFLOW_SUBMIT_URL, SILICONFLOW_STATUS_URL,
    DEFAULT_HEADERS, REQUEST_TIMEOUT, IMAGE_SIZE
)

def submit_video(prompt: str) -> Optional[str]:
    if not SILICONFLOW_API_TOKEN:
        return None
    try:
        r = requests.post(
            SILICONFLOW_SUBMIT_URL,
            headers=DEFAULT_HEADERS,
            json={"model": TEXT_TO_VIDEO_MODEL, "prompt": prompt, "image_size" : IMAGE_SIZE},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("requestId")
    except Exception:
        return None

def check_status(request_id: str) -> Dict[str, Any]:
    if not SILICONFLOW_API_TOKEN:
        return {"status": "Error", "error": "Missing API token"}
    try:
        r = requests.post(
            SILICONFLOW_STATUS_URL,
            headers=DEFAULT_HEADERS,
            json={"requestId": request_id},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "Error", "error": str(e)}

def download_to(url: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as r:
        r.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if chunk: f.write(chunk)
