from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class ScriptItem:
    text: str
    method: str
    prompt: str
    filename: str | None = None  # optional target file basename

@dataclass
class InputSpec:
    project: str
    script: List[ScriptItem]

@dataclass
class RunResult:
    ok: bool
    index: int
    item: ScriptItem
    method: str
    artifacts: List[str]
    meta: Dict[str, Any]
    error: str | None = None
