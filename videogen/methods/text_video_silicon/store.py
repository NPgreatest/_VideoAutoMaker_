import csv, threading
from pathlib import Path
from typing import Dict, List

class TaskCSV:
    _lock = threading.Lock()  # fine now, no nested locks

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            with open(self.db_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["request_id", "status", "output_path"])
                writer.writeheader()

    def get_all(self) -> List[Dict[str, str]]:
        if not self.db_path.exists():
            return []
        with open(self.db_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]

    def upsert(self, row: Dict[str, str]) -> None:
        with self._lock:
            rows = self.get_all()
            rid = row.get("request_id")
            updated = False
            for r in rows:
                if r.get("request_id") == rid:
                    r.update(row)
                    updated = True
                    break
            if not updated:
                rows.append(row)

            fieldnames = sorted(set().union(*(r.keys() for r in rows)))
            with open(self.db_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
                f.flush()

        print(f"[TaskCSV] ✅ Upserted {rid} (status={row.get('status')})")
