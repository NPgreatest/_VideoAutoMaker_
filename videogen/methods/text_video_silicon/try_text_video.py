#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from videogen.methods.text_video_silicon import TextVideoSilicon
from videogen.methods.text_video_silicon.constants import  DB_PATH

def main() -> None:
    """
    测试 TextVideoSilicon 模块。
    运行方式：
        python test_text_video_silicon.py
    """

    # 模拟工作目录
    workdir = Path("./_test_out").resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    # 创建模块实例
    method = TextVideoSilicon()

    # 定义测试参数
    project = "text_to_video_demo"
    target_name = "scene_intro"
    text = "生成一个关于人工智能未来的短片。"
    prompt = (
        "镜头从宇宙星空慢慢拉近到城市夜景，"
        "霓虹灯闪烁，展示热闹的湾区街景。"
    )

    print(f"[Test] Submitting text-to-video task to SiliconFlow...")
    result = method.run(
        prompt=prompt,
        project=project,
        target_name=target_name,
        text=text,
        workdir=workdir
    )

    print("\n=== RESULT ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    db_path = Path(DB_PATH)
    if db_path.exists():
        print(f"\n[OK] Database exists at: {db_path}")
        print(f"First few lines:")
        print("-" * 40)
        lines = db_path.read_text(encoding="utf-8").splitlines()
        for line in lines[:6]:
            print(line)
        print("-" * 40)
    else:
        print("[WARN] video_download.csv not found — submission may have failed.")

if __name__ == "__main__":
    main()
