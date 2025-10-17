#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from typing import List, Dict, Any

from method import ReactRenderMethod


def _pick_video_artifact(artifacts: List[str]) -> Path:
    """从 artifacts 里挑出视频文件（.mp4 或 .webm）。"""
    for p in artifacts:
        suf = Path(p).suffix.lower()
        if suf in (".mp4", ".webm"):
            return Path(p)
    # 兜底：如果没找到（理论上不会），返回最后一个
    return Path(artifacts[-1])


def test_llm_render_suite(out_root: Path) -> None:
    """
    LLM JSX→视频 渲染测试（多场景 & 不同时长）
    场景涵盖：标题卡/时间轴/架构图/数据图表
    """
    print("[Test] Starting LLM React rendering suite...")

    m = ReactRenderMethod()

    # 4 个示例场景（你可按需增删改）
    scenarios: List[Dict[str, Any]] = [
        {
            "name": "scene_title_card",
            "narration": "Title card with radar sweep",
            "text": (
                "Create a React scene: a cinematic title card for 'MH370'. "
                "Centered bold title, subtle grid background, and a rotating radar sweep arc. "
                "Typewriter-like title reveal, gentle vignette."
            ),
            "duration_ms": 5000,  # 5s
        },
        {
            "name": "scene_architecture",
            "narration": "Microservice architecture diagram",
            "text": (
                "Render a simple architecture diagram: boxes for 'Client', 'API', and 'DB' "
                "connected by animated arrows. Pulse highlight on 'API' every second; "
                "labels fade in; subtle node hover glow."
            ),
            "duration_ms": 7000,  # 7s
        },
        {
            "name": "scene_timeline",
            "narration": "2014-2018 timeline",
            "text": (
                "Visualize a horizontal timeline from 2014 to 2018. "
                "Milestone dots slide in left-to-right with labels: 2014, 2015, 2016, 2017, 2018. "
                "An indicator smoothly moves along the line."
            ),
            "duration_ms": 8000,  # 8s
        },
        {
            "name": "scene_charts",
            "narration": "Passenger composition chart",
            "text": (
                "Draw a donut chart showing 239 total people: 227 passengers and 12 crew. "
                "Numbers count up, slices animate from 0 to target angles, and a legend appears on the right."
            ),
            "duration_ms": 6000,  # 6s
        },
    ]

    project = "react_suite_tests"

    for i, sc in enumerate(scenarios, 1):
        print(f"\n[Test] Running scenario {i}/{len(scenarios)}: {sc['name']} ...")
        res = m.run(
            prompt=sc["narration"],
            project=project,
            target_name=sc["name"],
            text=sc["text"],
            workdir=out_root,
            duration_ms=sc["duration_ms"],
        )

        if not res.get("ok"):
            raise SystemExit(f"[Error] Scenario '{sc['name']}' failed: {res.get('error')}")

        artifacts = res.get("artifacts", [])
        if not artifacts:
            raise SystemExit(f"[Error] Scenario '{sc['name']}' returned no artifacts")

        video_path = _pick_video_artifact(artifacts)
        html_path = next((Path(p) for p in artifacts if p.endswith("index.html")), None)

        size = video_path.stat().st_size if video_path.exists() else 0
        print(f"[OK] {sc['name']}: video={video_path} size={size} bytes; html={html_path}")
        meta = res.get("meta", {})
        print(f"[Meta] durationMs={meta.get('durationMs')} tool={meta.get('syntax_tool')} attempts={meta.get('attempts')}")


def main():
    ap = argparse.ArgumentParser(description="Test React rendering and LLM integration with multiple scenarios.")
    ap.add_argument("--out", default="./_test_out", help="Output directory root for generated files.")
    args = ap.parse_args()

    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"[Info] Output root directory: {out_root}")

    test_llm_render_suite(out_root)


if __name__ == "__main__":
    main()
