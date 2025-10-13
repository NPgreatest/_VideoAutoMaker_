from __future__ import annotations
import csv, shutil, threading
from pathlib import Path
from typing import Dict, List, Optional

CSV_FIELDS = [
    "request_id","project","target_name","prompt","model","status",
    "output_path","source_url","created_ts","updated_ts","error","poll_count","workdir",
]

class TaskCSV:
    """线程安全 + 原子写入的 CSV 小库"""
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._rows: Dict[str, Dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.db_path.exists():
            with self.db_path.open("w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
            return
        with self.db_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self._rows[row["request_id"]] = row

    def _flush(self) -> None:
        tmp = self.db_path.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            for r in self._rows.values(): w.writerow(r)
        shutil.move(str(tmp), str(self.db_path))  # 原子替换

    def upsert(self, row: Dict[str, str]) -> None:
        with self._lock:
            norm = {k: "" for k in CSV_FIELDS}
            for k, v in row.items():
                if k in norm: norm[k] = "" if v is None else str(v)
            self._rows[norm["request_id"]] = norm
            self._flush()

    def get_all(self) -> List[Dict[str, str]]:
        with self._lock:
            return list(self._rows.values())

    def get(self, request_id: str) -> Optional[Dict[str, str]]:
        with self._lock:
            return self._rows.get(request_id)
