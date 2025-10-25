#!/usr/bin/env python3
from __future__ import annotations

import os.path
import time
import random
from datetime import datetime, timezone
from pathlib import Path

from dacite import from_dict
from dotenv import load_dotenv

from videogen.methods.audio_engine.utils import get_total_audio_duration_ms
from videogen.methods.registry import create_method
import videogen.methods  # This ensures all methods are registered
from videogen.pipeline.schema import ScriptBlock, Decision, GenerationResult
from videogen.pipeline.utils import read_json, write_json
from videogen.router.decider import decide_generation_method

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
            audioPath = block.audioGeneration.meta['audio_path']
            project_dir = workdir / "project" / project
            fullPath = project_dir / audioPath
            totalDuration = get_total_audio_duration_ms(fullPath)

        if genAudio:
            audioMethod = create_method('silicon_audio')
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
                # Retry logic for API rate limits
                max_retries = 3
                base_delay = 2.0
                
                for attempt in range(max_retries):
                    try:
                        result = method.run(
                            prompt=block.prompt,
                            project=project,
                            target_name=block.id,
                            text=block.text,
                            workdir=workdir,
                            duration_ms=totalDuration,
                            block=block,
                        )
                        break  # Success, exit retry loop
                    except Exception as e:
                        if attempt == max_retries - 1:
                            # Last attempt failed, re-raise the exception
                            raise e
                        
                        # Check if it's a retryable error
                        error_msg = str(e).lower()
                        retryable_keywords = [
                            'rate limit', 'too many requests', '429', 'throttle',
                            'timeout', 'connection', 'network', 'temporary',
                            'service unavailable', '502', '503', '504'
                        ]
                        
                        if any(keyword in error_msg for keyword in retryable_keywords):
                            delay = base_delay * (2 ** attempt) + random.uniform(0, 2)
                            print(f"⚠️  Retryable error for {block.id}: {e}")
                            print(f"    Retrying in {delay:.2f}s... (attempt {attempt + 1}/{max_retries})")
                            time.sleep(delay)
                        else:
                            # Not a retryable error, re-raise immediately
                            print(f"❌ Non-retryable error for {block.id}: {e}")
                            raise e

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
        
        # Small delay between video generation requests to prevent rate limiting
        if genMedia and block.decision.method == "text_video_silicon":
            delay = random.uniform(1.0, 3.0)
            print(f"⏸️  Waiting {delay:.1f}s before next request to avoid rate limits...")
            time.sleep(delay)

    print("\n✅ Pipeline finished.")


if __name__ == "__main__":
    run_pipeline(Path(f"./project/{PROJECT_NAME}/{PROJECT_NAME}.json"), Path("."), True,False   ,True , True)
