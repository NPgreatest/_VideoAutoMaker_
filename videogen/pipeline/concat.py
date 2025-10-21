#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess, shlex
from pathlib import Path
from typing import List
from dacite import from_dict
from dotenv import load_dotenv

from videogen.pipeline.schema import ScriptBlock
from videogen.pipeline.utils import read_json, write_json


# ==========================================
# 🔧 Helpers
# ==========================================

def _run_ffmpeg(cmd: List[str]) -> bool:
    """Run FFmpeg and print output on failure."""
    print(f"[ffmpeg] Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("[ffmpeg] ❌ Failed:")
        print("---- STDOUT ----")
        print(proc.stdout)
        print("---- STDERR ----")
        print(proc.stderr)
        print("----------------")
        return False
    return True


# ==========================================
# 🔊 Merge WAVs
# ==========================================
def _concat_wavs_with_ffmpeg(wav_paths: List[Path], out_path: Path) -> bool:
    """安全拼接多个 WAV 文件并重新编码，确保音频数据连续有效。"""
    if not wav_paths:
        print("[concat] ⚠️ No wavs to merge.")
        return False

    lst = out_path.with_suffix(".txt")
    lines = [f"file '{p.resolve()}'" for p in wav_paths]
    lst.write_text("\n".join(lines), encoding="utf-8")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(lst.resolve()),
        "-ac", "2",               # 转为双声道
        "-ar", "44100",           # 重采样为标准采样率
        "-c:a", "pcm_s16le",      # 无损 PCM
        str(out_path.resolve()),
    ]
    print(f"[concat] 🔊 Safely merging {len(wav_paths)} WAVs → {out_path.name}")
    ok = _run_ffmpeg(cmd)
    lst.unlink(missing_ok=True)
    if ok:
        print(f"[concat] ✅ Safe WAV merged → {out_path}")
    else:
        print(f"[concat] ❌ Failed to merge WAVs safely.")
    return ok


# ==========================================
# 🎞️ Per-clip Mux (Audio + Video)
# ==========================================
def _mux_audio_video(video_path: Path, audio_path: Path, out_path: Path) -> bool:
    """将单个 clip 的音频与视频合成，确保每个片段内部同步。"""
    if not video_path.exists() or not audio_path.exists():
        print(f"[mux] ⚠️ Missing {video_path.name} or {audio_path.name}, skipping mux.")
        return False

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path.resolve()),
        "-i", str(audio_path.resolve()),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",                # 不重新编码画面
        "-c:a", "aac", "-b:a", "192k", # 转为标准 AAC
        "-ac", "2", "-ar", "44100",    # 立体声 + 44.1kHz
        "-shortest",
        str(out_path.resolve())
    ]
    print(f"[mux] 🎬 Muxing {video_path.name} + {audio_path.name} → {out_path.name}")
    ok = _run_ffmpeg(cmd)
    if ok:
        print(f"[mux] ✅ Muxed clip created: {out_path.name}")
    return ok


# ==========================================
# 🎬 Concat Final Muxed Clips
# ==========================================
def _concat_videos_with_ffmpeg(video_paths: List[Path], out_path: Path) -> bool:
    """Concatenate pre-muxed MP4 videos (each with synced audio)."""
    if not video_paths:
        print("[concat] ⚠️ No videos to merge.")
        return False

    lst = out_path.with_suffix(".txt")
    lines = [f"file '{p.resolve()}'" for p in video_paths]
    lst.write_text("\n".join(lines), encoding="utf-8")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(lst.resolve()),
        "-c", "copy",
        str(out_path.resolve()),
    ]
    print(f"[concat] 🎞️ Merging {len(video_paths)} muxed clips → {out_path}")
    ok = _run_ffmpeg(cmd)
    lst.unlink(missing_ok=True)
    if ok:
        print(f"[concat] ✅ Final muxed video: {out_path}")
    else:
        print(f"[concat] ❌ Failed to concat muxed clips.")
    return ok


# ==========================================
# 🧩 Main Pipeline
# ==========================================
def concat_project_media(json_path: Path, workdir: Path) -> None:
    """Merge all audio and video segments for a project into final outputs (with sync)."""
    print(f"🎬 Starting concat for {json_path}")
    raw = read_json(json_path)
    project_name = raw.get("project")
    project_dir = workdir / "project" / project_name

    blocks = [from_dict(ScriptBlock, b) for b in raw.get("script", [])]
    audio_files, video_files = [], []

    for b in blocks:
        # -------- Collect audio --------
        if b.audioGeneration and b.audioGeneration.ok:
            merged_audio = b.audioGeneration.meta.get("merged")
            if merged_audio:
                audio_files.append(project_dir / merged_audio)

        # -------- Collect video --------
        if b.generation and b.generation.ok:
            video_meta = b.generation.meta
            video_file = video_meta.get("video") or video_meta.get("output_path")
            if video_file:
                p = Path(video_file)
                if not p.is_absolute() and str(p).startswith("project/"):
                    video_files.append(workdir / p)
                else:
                    video_files.append(project_dir / p)

    print(f"[concat] Found {len(audio_files)} audio + {len(video_files)} video clips.")
    if len(audio_files) != len(video_files):
        print(f"[warn] ⚠️ Number mismatch! audio={len(audio_files)} vs video={len(video_files)}")

    # -------- Step 1: per-clip mux --------
    muxed_clips = []
    for i, (a, v) in enumerate(zip(audio_files, video_files)):
        muxed_out = project_dir / f"L{i+1}_muxed.mp4"
        if _mux_audio_video(v, a, muxed_out):
            muxed_clips.append(muxed_out)

    # -------- Step 2: global concat --------
    final_muxed = project_dir / f"{project_name}_final_muxed.mp4"
    if _concat_videos_with_ffmpeg(muxed_clips, final_muxed):
        raw["final_muxed"] = str(final_muxed.relative_to(workdir))

    # -------- Step 3: backup individual outputs (optional) --------
    final_audio = project_dir / f"{project_name}_final.wav"
    final_video = project_dir / f"{project_name}_final.mp4"

    # 拼接纯音频（方便分析）
    _concat_wavs_with_ffmpeg(audio_files, final_audio)
    raw["final_audio"] = str(final_audio.relative_to(workdir))

    # 拼接纯视频（无声版参考）
    _concat_videos_with_ffmpeg(video_files, final_video)
    raw["final_video"] = str(final_video.relative_to(workdir))

    # -------- Save updated JSON --------
    write_json(json_path, raw)
    print(f"✅ Concat complete for {project_name}")
    print(f"   → Audio: {final_audio.exists()} | Video: {final_video.exists()} | Muxed: {final_muxed.exists()}")


# ==========================================
# 🧠 Entrypoint
# ==========================================
load_dotenv()
PROJECT_NAME = os.getenv("PROJECT_NAME")

if __name__ == "__main__":
    concat_project_media(
        Path(f"./project/{PROJECT_NAME}/{PROJECT_NAME}.json"),
        Path(".")
    )
