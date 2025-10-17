#!/usr/bin/env python3
from __future__ import annotations
import subprocess, shlex
from pathlib import Path
from typing import List
from dacite import from_dict

from videogen.pipeline.schema import ScriptBlock
from videogen.pipeline.utils import read_json, write_json

# --------------------------
# Helpers
# --------------------------

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


def _concat_wavs_with_ffmpeg(wav_paths: List[Path], out_path: Path) -> bool:
    """Concatenate multiple WAVs safely."""
    if not wav_paths:
        print("[concat] ⚠️ No wavs to merge.")
        return False

    lst = out_path.with_suffix(".txt")
    lines = [f"file {shlex.quote(str(p.resolve()))}" for p in wav_paths]
    lst.write_text("\n".join(lines), encoding="utf-8")

    cmd_copy = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(lst.resolve()),
        "-c", "copy",
        str(out_path.resolve())
    ]
    if _run_ffmpeg(cmd_copy):
        print(f"[concat] ✅ WAV merged (copy) → {out_path}")
        lst.unlink(missing_ok=True)
        return True

    cmd_reencode = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(lst.resolve()),
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
        str(out_path.resolve())
    ]
    ok = _run_ffmpeg(cmd_reencode)
    lst.unlink(missing_ok=True)
    if ok:
        print(f"[concat] ✅ WAV merged (re-encoded) → {out_path}")
    return ok


def _concat_videos_with_ffmpeg(video_paths: List[Path], out_path: Path) -> bool:
    """Concatenate MP4 videos using FFmpeg concat demuxer with absolute paths."""
    if not video_paths:
        print("[concat] ⚠️ No videos to merge.")
        return False

    lst = out_path.with_suffix(".txt")
    lines = [f"file {shlex.quote(str(p.resolve()))}" for p in video_paths]
    lst.write_text("\n".join(lines), encoding="utf-8")

    print(f"[concat] List file content:\n{lst.read_text()}\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(lst.resolve()),
        "-c", "copy",
        str(out_path.resolve()),
    ]

    ok = _run_ffmpeg(cmd)
    lst.unlink(missing_ok=True)
    if ok:
        print(f"[concat] ✅ MP4 merged → {out_path}")
    else:
        print("[concat] ⚠️ MP4 concat failed. Try inspecting the .txt list manually.")
    return ok


def _mux_audio_video(video_path: Path, audio_path: Path, out_path: Path) -> bool:
    """Combine final video and audio into one MP4 with synchronized tracks."""
    if not video_path.exists() or not audio_path.exists():
        print("[mux] ⚠️ Missing final audio or video, skipping mux.")
        return False

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path.resolve()),
        "-i", str(audio_path.resolve()),
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(out_path.resolve()),
    ]
    print(f"[mux] Merging {video_path.name} + {audio_path.name} → {out_path.name}")
    ok = _run_ffmpeg(cmd)
    if ok:
        print(f"[mux] ✅ Created muxed video → {out_path}")
    return ok


# --------------------------
# Main entry
# --------------------------

def concat_project_media(json_path: Path, workdir: Path) -> None:
    """Merge all audio and video segments for a project into final outputs."""
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
                # Avoid double prefix project/mh370_demo/project/mh370_demo
                if not p.is_absolute() and str(p).startswith("project/"):
                    video_files.append(workdir / p)
                else:
                    video_files.append(project_dir / p)

    print("[concat] Video files resolved:")
    for v in video_files:
        print("  ", v)

    final_audio = project_dir / f"{project_name}_final.wav"
    final_video = project_dir / f"{project_name}_final.mp4"
    final_muxed = project_dir / f"{project_name}_final_muxed.mp4"

    print(f"[concat] Found {len(audio_files)} audio clips, {len(video_files)} videos.")

    if _concat_wavs_with_ffmpeg(audio_files, final_audio):
        raw["final_audio"] = str(final_audio.relative_to(workdir))

    if _concat_videos_with_ffmpeg(video_files, final_video):
        raw["final_video"] = str(final_video.relative_to(workdir))

    # -------- Combine Audio + Video --------
    if final_audio.exists() and final_video.exists():
        if _mux_audio_video(final_video, final_audio, final_muxed):
            raw["final_muxed"] = str(final_muxed.relative_to(workdir))

    # -------- Save updated JSON --------
    write_json(json_path, raw)
    print(f"✅ Concat complete for {project_name}")
    print(f"   → Audio: {final_audio.exists()} | Video: {final_video.exists()} | Muxed: {final_muxed.exists()}")


if __name__ == "__main__":
    concat_project_media(
        Path("./project/mh370_demo/mh370_demo.json"),
        Path(".")
    )
