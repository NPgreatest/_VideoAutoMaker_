#!/usr/bin/env python3
from __future__ import annotations
"""
High‑quality, robust concat pipeline for mixed‑spec clips (React + Model outputs).
Goals:
- Auto‑detect target spec from inputs (max resolution, majority/maximum fps).
- Normalize every clip to EXACT same spec (size, fps, pixel format, codec, SAR/DAR, colorspace).
- Prefer lossless final concat (c=copy) once clips are uniform; fallback to safe re‑encode if needed.
- Rebuild PTS and avoid negative timestamps to prevent stutter / missing clips.
- Keep high quality: x264 -preset slow -crf 14 (tunable), yuv420p.

Usage:
  export PROJECT_NAME=mh370_mid
  python concat_high_quality.py

Requires: ffmpeg, ffprobe
"""

import json
import math
import os
import re
import shlex
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dacite import from_dict
from dotenv import load_dotenv

# If you don't have these in your env/project, you can stub them or replace with your own.
from videogen.pipeline.schema import ScriptBlock
from videogen.pipeline.utils import read_json, write_json

HERE = Path(__file__).resolve().parent

# ====== Tunables ======
CRF = os.getenv("CONCAT_CRF", "14")  # Lower = better quality, bigger size (14~18 recommended)
PRESET = os.getenv("CONCAT_PRESET", "slow")
AUDIO_RATE = os.getenv("AUDIO_RATE", "44100")
AUDIO_BR = os.getenv("AUDIO_BR", "192k")
PIX_FMT = os.getenv("PIX_FMT", "yuv420p")
# To hard‑limit max output resolution (e.g., 1920x1080), set envs; otherwise auto = max of inputs
MAX_W = int(os.getenv("MAX_WIDTH", "0"))
MAX_H = int(os.getenv("MAX_HEIGHT", "0"))
# If you want to force FPS, set FORCE_FPS; otherwise auto from inputs
FORCE_FPS = os.getenv("FORCE_FPS")  # e.g., "30" or "60" or None

# ====== Helpers ======

def run(cmd: List[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def ffprobe_streams(path: Path) -> Dict:
    cmd = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-print_format", "json", str(path)
    ]
    rc, out, err = run(cmd)
    if rc != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {err}")
    return json.loads(out)


def parse_fps(r_frame_rate: str) -> Optional[float]:
    # e.g., "30000/1001"
    if not r_frame_rate or r_frame_rate == "0/0":
        return None
    try:
        if "/" in r_frame_rate:
            n, d = r_frame_rate.split("/")
            return float(n) / float(d)
        return float(r_frame_rate)
    except Exception:
        return None


@dataclass
class ClipInfo:
    path: Path
    w: int
    h: int
    fps: float
    pix_fmt: str
    sar: Tuple[int, int]
    codec: str
    has_audio: bool


def get_clip_info(path: Path) -> ClipInfo:
    data = ffprobe_streams(path)
    vstreams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    astreams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not vstreams:
        raise ValueError(f"No video stream in {path}")
    v = vstreams[0]
    w = int(v.get("width", 0))
    h = int(v.get("height", 0))
    fps = parse_fps(v.get("r_frame_rate") or v.get("avg_frame_rate")) or 30.0
    pix_fmt = v.get("pix_fmt", "")
    sar_num = int(v.get("sample_aspect_ratio", "1:1").split(":")[0]) if v.get("sample_aspect_ratio") else 1
    sar_den = int(v.get("sample_aspect_ratio", "1:1").split(":")[1]) if v.get("sample_aspect_ratio") else 1
    codec = v.get("codec_name", "")
    return ClipInfo(path=path, w=w, h=h, fps=fps, pix_fmt=pix_fmt, sar=(sar_num, sar_den), codec=codec, has_audio=bool(astreams))


def choose_target_spec(infos: List[ClipInfo]) -> tuple[int, int, int]:
    """Pick target (W, H, FPS):
    - W,H = max of inputs (optionally capped by MAX_W/MAX_H if set)
    - FPS = if FORCE_FPS set -> that; else most common integer-rounded fps; tie -> higher
    """
    max_w = max(i.w for i in infos)
    max_h = max(i.h for i in infos)
    if MAX_W and max_w > MAX_W:
        max_w = MAX_W
    if MAX_H and max_h > MAX_H:
        max_h = MAX_H

    if FORCE_FPS:
        target_fps = int(round(float(FORCE_FPS)))
    else:
        counter = Counter(int(round(i.fps)) for i in infos if i.fps)
        # Prefer a widely used FPS; if tie, take the higher
        most_common = counter.most_common()
        target_fps = most_common[0][0] if most_common else 30
        if len(most_common) > 1 and most_common[1][1] == most_common[0][1]:
            target_fps = max(most_common[0][0], most_common[1][0])

    return max_w, max_h, target_fps


def normalized_name(p: Path, w: int, h: int, fps: int) -> Path:
    return p.with_name(f"norm_{p.stem}_{w}x{h}_{fps}fps.mp4")


def normalize_clip(src: Path, dst: Path, w: int, h: int, fps: int) -> bool:
    """Normalize a single clip to exact W,H,FPS, pixel format, codec, SAR=1:1, rebuild PTS.
    Use high quality x264 settings.
    """
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={fps},format={PIX_FMT}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts", "-avoid_negative_ts", "make_zero",
        "-i", str(src),
        "-map", "0:v:0?", "-map", "0:a:0?",
        "-vf", vf,
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-pix_fmt", PIX_FMT,
        "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-c:a", "aac", "-ar", AUDIO_RATE, "-b:a", AUDIO_BR,
        "-movflags", "+faststart",
        str(dst),
    ]
    rc, out, err = run(cmd)
    if rc != 0:
        print(f"[normalize] ❌ {src.name}: {err[-400:]}")
        return False
    print(f"[normalize] ✅ {dst.name}")
    return True


def concat_copy(listfile: Path, out_path: Path) -> bool:
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c", "copy", "-movflags", "+faststart",
        str(out_path)
    ]
    rc, out, err = run(cmd)
    if rc != 0:
        print(f"[concat-copy] ❌ {err[-400:]}")
        return False
    print(f"[concat-copy] ✅ {out_path.name}")
    return True


def concat_safe_reencode(listfile: Path, out_path: Path, fps: int) -> bool:
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-vf", f"fps={fps},format={PIX_FMT}",
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-pix_fmt", PIX_FMT,
        "-c:a", "aac", "-ar", AUDIO_RATE, "-b:a", AUDIO_BR,
        "-fflags", "+genpts", "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        str(out_path)
    ]
    rc, out, err = run(cmd)
    if rc != 0:
        print(f"[concat-reencode] ❌ {err[-400:]}")
        return False
    print(f"[concat-reencode] ✅ {out_path.name}")
    return True


# ====== Subtitles utilities (unchanged, but safer) ======
TIME_RE = re.compile(r"(\d\d:\d\d:\d\d,\d{3}) --> (\d\d:\d\d:\d\d,\d{3})")

def parse_srt_time(t: str) -> float:
    h, m, s_ms = t.split(":")
    s, ms = s_ms.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def combine_srt_files(input_files: List[Path], output_file: Path) -> None:
    print(f"[srt] Merging {len(input_files)} files → {output_file.name}")
    all_entries, total_offset, counter = [], 0.0, 1
    for srt_file in input_files:
        if not srt_file.exists():
            continue
        content = srt_file.read_text(encoding="utf-8").strip()
        blocks = re.split(r"\n\s*\n", content)
        local_start, local_end = None, 0.0
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue
            m = TIME_RE.match(lines[1])
            if not m:
                continue
            start, end = m.groups()
            s, e = parse_srt_time(start), parse_srt_time(end)
            if local_start is None:
                local_start = s
            s_rel, e_rel = s - local_start, e - local_start
            local_end = max(local_end, e_rel)
            all_entries.append((counter, format_srt_time(s_rel + total_offset), format_srt_time(e_rel + total_offset), "\n".join(lines[2:])))
            counter += 1
        total_offset += local_end
    with output_file.open("w", encoding="utf-8") as f:
        for idx, s, e, text in all_entries:
            f.write(f"{idx}\n{s} --> {e}\n{text}\n\n")
    print(f"[srt] ✅ {output_file}")


# ====== Project pipeline ======

def collect_project_clips(raw: Dict, workdir: Path) -> List[Path]:
    from videogen.pipeline.schema import ScriptBlock
    blocks = [from_dict(ScriptBlock, b) for b in raw.get("script", [])]
    project_name = raw.get("project")
    project_dir = workdir / "project" / project_name

    muxed = []
    for i, b in enumerate(blocks, start=1):
        # Prefer pre‑muxed per your pipeline; if not present, fall back to generated video
        mux_path = project_dir / f"L{i}_muxed.mp4"
        if mux_path.exists():
            muxed.append(mux_path)
            continue
        # Fallback to generation meta
        v = None
        if b.generation and b.generation.ok:
            meta = b.generation.meta
            path = meta.get("video") or meta.get("output_path")
            if path:
                p = Path(path)
                if not p.is_absolute():
                    p = (workdir / p) if str(p).startswith("project/") else (project_dir / p)
                v = p
        if v and v.exists():
            muxed.append(v)
    return muxed


def normalize_all(clips: List[Path], outdir: Path, w: int, h: int, fps: int) -> List[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    normalized = []
    for p in clips:
        dst = outdir / normalized_name(p, w, h, fps).name
        ok = normalize_clip(p, dst, w, h, fps)
        if ok:
            normalized.append(dst)
    return normalized


def write_concat_list(paths: List[Path], listfile: Path) -> None:
    listfile.write_text("\n".join(f"file '{p.resolve()}'" for p in paths), encoding="utf-8")


def concat_project_media(json_path: Path, workdir: Path) -> None:
    print(f"🎬 Starting concat for {json_path}")
    raw = read_json(json_path)
    project_name = raw.get("project")
    project_dir = workdir / "project" / project_name
    outdir = project_dir / "_norm"

    # 1) Collect candidate clips (prefer muxed per block)
    clips = collect_project_clips(raw, workdir)
    if not clips:
        raise SystemExit("No clips found to concat.")

    # 2) Analyze and choose target spec
    infos = [get_clip_info(p) for p in clips]
    target_w, target_h, target_fps = choose_target_spec(infos)
    print(f"[spec] Target: {target_w}x{target_h} @ {target_fps}fps, pix_fmt={PIX_FMT}")

    # 3) Normalize all clips to the exact same spec
    norm_clips = normalize_all(clips, outdir, target_w, target_h, target_fps)
    if not norm_clips:
        raise SystemExit("Normalization failed for all clips.")

    # 4) Concat with stream‑copy (no extra re‑encode) for best quality
    concat_list = project_dir / f"{project_name}_concat_list.txt"
    write_concat_list(norm_clips, concat_list)

    final_copy = project_dir / f"{project_name}_final_muxed_copy.mp4"
    if not concat_copy(concat_list, final_copy):
        # 5) Fallback: safe re‑encode concat (still high quality)
        final_safe = project_dir / f"{project_name}_final_muxed_safe.mp4"
        ok = concat_safe_reencode(concat_list, final_safe, target_fps)
        if ok:
            raw["final_muxed"] = str(final_safe.relative_to(workdir))
        else:
            raise SystemExit("Concat failed (copy and reencode).")
    else:
        raw["final_muxed"] = str(final_copy.relative_to(workdir))

    # 6) Optional: pure video concat from source generations (debug)
    final_video_debug = project_dir / f"{project_name}_video_only_debug.mp4"
    if not final_video_debug.exists():
        # Reuse normalized (video+audio) but drop audio on output to inspect video timing
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-an", "-c:v", "copy", str(final_video_debug)
        ]
        rc, out, err = run(cmd)
        if rc == 0:
            raw["final_video_debug"] = str(final_video_debug.relative_to(workdir))

    # 7) Merge & burn subtitles if present
    subtitles_dir = project_dir / "subtitles"
    srt_files = sorted(subtitles_dir.glob("L*.srt"), key=lambda p: int(re.search(r"L(\d+)", p.stem).group(1)))
    if srt_files and "final_muxed" in raw:
        output_srt = project_dir / f"{project_name}_full.srt"
        combine_srt_files(srt_files, output_srt)
        burned_video = project_dir / f"{project_name}_with_subs.mp4"
        # Burn into the final muxed output (copy or safe)
        final_path = workdir / raw["final_muxed"]
        font_path = Path("./assets/microhei.ttc").resolve()
        if font_path.exists():
            subtitles_filter = (
                f"subtitles='{output_srt}':"
                f"force_style='FontName={font_path.stem},FontSize=21,"
                f"PrimaryColour=&Hffffff&,OutlineColour=&H000000&,BorderStyle=1,"
                f"Outline=2,Shadow=0,MarginV=50,Alignment=2'"
            )
            cmd = [
                "ffmpeg", "-y", "-i", str(final_path),
                "-vf", subtitles_filter,
                "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
                "-pix_fmt", PIX_FMT,
                "-c:a", "copy",
                str(burned_video)
            ]
            rc, out, err = run(cmd)
            if rc == 0:
                raw["final_burned"] = str(burned_video.relative_to(workdir))
                print(f"[burn] ✅ {burned_video.name}")
            else:
                print(f"[burn] ⚠️ Burn failed: {err[-400:]}")
        else:
            print("[burn] ⚠️ Font not found, skip burning.")

    write_json(json_path, raw)
    print(f"✅ All concat steps complete for {project_name}")


# ====== Entrypoint ======
load_dotenv()
PROJECT_NAME = os.getenv("PROJECT_NAME")

if __name__ == "__main__":
    if not PROJECT_NAME:
        raise SystemExit("Please set PROJECT_NAME in env.")
    concat_project_media(
        Path(f"./project/{PROJECT_NAME}/{PROJECT_NAME}.json"),
        Path(".")
    )
