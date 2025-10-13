from __future__ import annotations
import json, time, threading
from pathlib import Path
from typing import Dict

from videogen.methods.text_video_silicon.constants import (
    POLL_INTERVAL_SEC, MAX_POLLS_PER_TASK,
    STATUS_SUCCEED, STATUS_ERROR, NON_TERMINAL, TERMINAL,
)
from videogen.methods.text_video_silicon.sf_api import check_status, download_to
from videogen.methods.text_video_silicon.store import TaskCSV

_worker_started: Dict[str, bool] = {}
_worker_guard = threading.Lock()

def start_background_worker(store: TaskCSV) -> None:
    """每个 CSV（以绝对路径为 key）只启动一次线程"""
    key = str(store.db_path.resolve())
    with _worker_guard:
        if _worker_started.get(key): return
        th = threading.Thread(target=_loop, args=(store,), daemon=True, name=f"sf-poller:{key}")
        th.start()
        _worker_started[key] = True

def _loop(store: TaskCSV) -> None:
    print(f"[Worker] Polling loop started for {store.db_path}")
    idle_rounds = 0  # 连续检测到所有任务完成的轮数
    while True:
        rows = store.get_all()
        now = time.time()

        if not rows:
            print("[Worker] No tasks in CSV. Sleeping...")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        # 检查终止任务数量
        total = len(rows)
        done = sum(1 for r in rows if r.get("status") in TERMINAL)
        print(f"[Worker] Checking {total} tasks ({done} done, {total - done} active)...")

        if done == total:
            idle_rounds += 1
            print(f"[Worker] All tasks complete ({idle_rounds}/3)...")
            if idle_rounds >= 3:
                print("[Worker] ✅ All tasks finished. Exiting gracefully.")
                break
            time.sleep(POLL_INTERVAL_SEC)
            continue
        else:
            idle_rounds = 0  # reset if new active task detected

        for row in rows:
            status = row.get("status", "")
            rid = row.get("request_id", "?")
            poll_cnt = int(row.get("poll_count") or "0")

            if status in TERMINAL:
                continue

            print(f"  → [Task {rid}] status={status} poll={poll_cnt}")

            # --- 超时检查 ---
            if poll_cnt >= MAX_POLLS_PER_TASK:
                print(f"  [!] Task {rid} timed out after {MAX_POLLS_PER_TASK * POLL_INTERVAL_SEC}s")
                row.update({
                    "status": STATUS_ERROR,
                    "error": f"Timeout after {MAX_POLLS_PER_TASK * POLL_INTERVAL_SEC}s",
                    "updated_ts": str(now),
                    "poll_count": str(poll_cnt),
                })
                store.upsert(row)
                continue

            # --- 轮询 API 状态 ---
            try:
                resp = check_status(rid)
            except Exception as e:
                print(f"  [x] check_status failed: {e}")
                continue

            new_status = resp.get("status") or STATUS_ERROR

            # === 成功 ===
            if new_status == STATUS_SUCCEED:
                videos = (resp.get("results") or {}).get("videos") or []
                url = videos[0].get("url") if videos else None
                if not url:
                    print(f"  [x] Task {rid} succeeded but no video URL!")
                    row.update({
                        "status": STATUS_ERROR,
                        "error": "Succeed but no video url",
                        "updated_ts": str(now),
                        "poll_count": str(poll_cnt + 1),
                    })
                    store.upsert(row)
                    continue

                print(f"  [✓] Task {rid} succeeded, downloading video from {url}")
                workdir = Path(row["workdir"])
                out_mp4 = workdir / "project" / row["project"] / f"{row['target_name']}.mp4"

                try:
                    download_to(url, out_mp4)
                    print(f"      → Saved to {out_mp4}")
                    row.update({
                        "status": STATUS_SUCCEED,
                        "source_url": url,
                        "output_path": str(out_mp4),
                        "updated_ts": str(now),
                        "error": "",
                        "poll_count": str(poll_cnt + 1),
                    })
                    store.upsert(row)

                    meta = {
                        "request_id": rid,
                        "model": row.get("model"),
                        "prompt": row.get("prompt"),
                        "source_url": url,
                        "created": float(row.get("created_ts") or now),
                        "finished": now,
                    }
                    meta_path = out_mp4.with_suffix(".meta.json")
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, ensure_ascii=False, indent=2)
                    print(f"      → Meta saved: {meta_path}")

                except Exception as e:
                    print(f"  [x] Download error for {rid}: {e}")
                    row.update({
                        "status": STATUS_ERROR,
                        "error": f"Download error: {e}",
                        "updated_ts": str(now),
                        "poll_count": str(poll_cnt + 1),
                    })
                    store.upsert(row)

            # === 仍在进行中 ===
            elif new_status in NON_TERMINAL:
                print(f"  [·] Task {rid} still running ({new_status})")
                row.update({
                    "status": new_status,
                    "updated_ts": str(now),
                    "poll_count": str(poll_cnt + 1),
                })
                store.upsert(row)

            # === 失败 ===
            else:
                print(f"  [x] Task {rid} failed with status={new_status}")
                row.update({
                    "status": new_status,
                    "error": resp.get("error", ""),
                    "updated_ts": str(now),
                    "poll_count": str(poll_cnt + 1),
                })
                store.upsert(row)

        print(f"[Worker] Sleep {POLL_INTERVAL_SEC}s...\n")
        time.sleep(POLL_INTERVAL_SEC)



def main() -> None:
    """
    手动启动轮询后台线程。
    用法：
        python -m videogen.methods.text_video_silicon.worker
    或者：
        python worker.py
    """
    db_path = Path("./db/video_download.csv").resolve()
    if not db_path.exists():
        print(f"[!] CSV not found at {db_path}")
        print("请先通过 TextVideoSilicon 提交至少一个任务。")
        return

    print(f"[Worker] Starting polling loop for {db_path}")
    store = TaskCSV(db_path)

    try:
        _loop(store)
    except KeyboardInterrupt:
        print("\n[Worker] Stopped manually.")


if __name__ == "__main__":
    main()