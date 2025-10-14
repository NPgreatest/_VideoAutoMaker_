#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path

# 允许在项目根目录执行此脚本时正常导入
sys.path.append(str(Path(__file__).resolve().parent))

from videogen.methods.subtitle_only.method import SubtitleOnlyMethod


def main():
    print("[Test] 🎬 Testing SubtitleOnlyMethod...")

    # 初始化方法实例
    method = SubtitleOnlyMethod()

    # 测试参数
    workdir = Path("./_test_out")
    project = "demo_subtitle_only"
    target_name = "scene_01"
    text = "“晚安，马航三七零。” 对，这句平静到不能再平静的告别，是机长留给世界的最后话语。"
    duration_ms = 5000

    # 执行
    result = method.run(
        prompt="test subtitle video generation",
        project=project,
        target_name=target_name,
        text=text,
        workdir=workdir,
        duration_ms=duration_ms,
    )

    # 输出结果
    if result["ok"]:
        print("✅ Subtitle video generated successfully!")
        print(f"📂 Output file: {result['meta']['output_path']}")
    else:
        print("❌ Subtitle generation failed:")
        print(f"Error: {result['error']}")

    print("\n[Meta Info]")
    for k, v in result["meta"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
