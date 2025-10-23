#!/usr/bin/env python3
from __future__ import annotations

import os.path
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv

from videogen.methods import react_render, text_video_silicon, subtitle_only
from videogen.methods.audio_engine.utils import get_total_audio_duration_ms
from videogen.pipeline.schema import ProjectJSON, ScriptBlock, Decision, GenerationResult
from videogen.pipeline.utils import read_json, write_json
from videogen.methods.registry import create_method
from videogen.llm_engine import get_engine
from videogen.router.decider import decide_generation_method
from dacite import from_dict

load_dotenv()
PROJECT_NAME = os.getenv("PROJECT_NAME")


def run_pipeline(input_path: Path, workdir: Path,genDecision = False, genAudio = False, genPrompt = False, genMedia = False) -> None:
    print(f"🚀 Starting pipeline for: {input_path}")
    raw = read_json(input_path)

    project = raw.get("project", "demo_project")
    blocks = [from_dict(ScriptBlock, b) for b in raw.get("script", [])]

    for block in blocks:
        print(f"\n🎞️  Processing {block.id} | status={block.status}")



        # --- 决策阶段 ---
        if genDecision and (not block.decision or block.status == "regenerate"):
            method_name = decide_generation_method(block.text, project)
            block.decision = Decision(method=method_name, confidence=1.0, decided_by="llm")
            print(f"→ Decided method: {method_name}")


        # process Audio part
        totalDuration = None # duration is based from audio
        if block.audioGeneration and block.audioGeneration.ok:
            audioPath = block.audioGeneration.meta['merged']
            project_dir = workdir / "project" / project
            fullPath = project_dir / audioPath
            totalDuration = get_total_audio_duration_ms(fullPath)

        if genAudio:
            audioMethod = create_method('audio_engine')
            result = audioMethod.run(
                    prompt=block.prompt,
                    project=project,
                    target_name=block.id,
                    text=block.text,
                    workdir=workdir,
                    block=block,
                )
            block.audioGeneration = GenerationResult(
                ok=result.get("ok", False),
                artifacts=result.get("artifacts", []),
                meta=result.get("meta", {}),
                error=result.get("error"),
            )
            if block.audioGeneration.ok and 'total_duration' in block.audioGeneration.meta:
                totalDuration = block.audioGeneration.meta['total_duration']
            else:
                raise Exception(f"⚠️  Audio generation failed or missing total_duration for {block.id}")

        if block.status == "done" and (block.generation and 'output_path' in block.generation.meta and os.path.exists(block.generation.meta['output_path'])):
            print("→ Skipped (already done).")
            continue

        # --- Video Part ---
        try:
            method = create_method(block.decision.method)

            if not block.prompt:
                block.prompt = method.generate_prompt(block.text)

            if genMedia:
                result = method.run(
                    prompt=block.prompt,
                    project=project,
                    target_name=block.id,
                    text=block.text,
                    workdir=workdir,
                    duration_ms=totalDuration,
                    block = block,
                )

                block.generation = GenerationResult(
                    ok=result.get("ok", False),
                    artifacts=result.get("artifacts", []),
                    meta=result.get("meta", {}),
                    error=result.get("error"),
                )
                block.status = "done" if block.generation.ok else "error"

        except Exception as e:
            block.generation = GenerationResult(
                ok=False,
                artifacts=[],
                meta={},
                error=str(e),
            )
            block.status = "error"

        # --- 写回更新 ---
        raw["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        for i, b in enumerate(raw["script"]):
            if b["id"] == block.id:
                raw["script"][i] = block.to_dict()
                break

        write_json(input_path, raw)
        print(f"→ Updated JSON ({block.status})")

    print("\n✅ Pipeline finished.")


if __name__ == "__main__":
    run_pipeline(Path(f"./project/{PROJECT_NAME}/{PROJECT_NAME}.json"), Path("."), True,False,True , True)
