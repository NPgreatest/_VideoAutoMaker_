#!/usr/bin/env python3
from __future__ import annotations

import os
import re, subprocess, json
from pathlib import Path
from typing import List

from dotenv import load_dotenv


# ==========================
# 🔧 Basic Time Conversions
# ==========================
def parse_srt_time(time_str: str) -> float:
    """Convert 'HH:MM:SS,mmm' → seconds (float)."""
    h, m, s_ms = time_str.split(":")
    s, ms = s_ms.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def format_srt_time(seconds: float) -> str:
    """Convert seconds (float) → 'HH:MM:SS,mmm'."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


# ==========================
# 🎬 Combine SRT Files
# ==========================
def combine_srt_files(input_files: List[Path], output_file: Path) -> None:
    """Combine multiple .srt files into one continuous timeline."""
    print(f"🎬 [combine] Merging {len(input_files)} SRT files → {output_file}")
    all_entries = []
    total_offset = 0.0
    counter = 1

    for srt_file in input_files:
        if not srt_file.exists():
            print(f"⚠️ Missing file: {srt_file}")
            continue

        with srt_file.open("r", encoding="utf-8") as f:
            content = f.read().strip()

        blocks = re.split(r"\n\s*\n", content)
        print(f"[combine] Processing {srt_file.name}, {len(blocks)} blocks")

        local_end = 0.0
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

            match = re.match(r"(\d\d:\d\d:\d\d,\d{3}) --> (\d\d:\d\d:\d\d,\d{3})", lines[1])
            if not match:
                continue
            start, end = match.groups()

            start_s = parse_srt_time(start) + total_offset
            end_s = parse_srt_time(end) + total_offset
            local_end = max(local_end, parse_srt_time(end))

            text_lines = lines[2:]
            all_entries.append((
                counter,
                format_srt_time(start_s),
                format_srt_time(end_s),
                "\n".join(text_lines),
            ))
            counter += 1

        total_offset += local_end

    with output_file.open("w", encoding="utf-8") as f:
        for idx, start, end, text in all_entries:
            f.write(f"{idx}\n{start} --> {end}\n{text}\n\n")

    print(f"✅ [combine] Combined {len(all_entries)} subtitles → {output_file}")


# ==========================
# 📺 Video Normalization
# ==========================
def probe_video_info(video_path: Path) -> dict:
    """Get resolution, fps, pixel format via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,pix_fmt",
        "-of", "json", str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)["streams"][0]
    fps = eval(data["r_frame_rate"])
    return {
        "width": data["width"],
        "height": data["height"],
        "fps": round(fps, 2),
        "pix_fmt": data["pix_fmt"],
    }

def find_highest_quality(videos: List[Path]) -> dict:
    """Find the highest resolution among a list of videos."""
    infos = [probe_video_info(v) for v in videos]
    best = max(infos, key=lambda x: x["width"] * x["height"])
    print(f"🎥 [normalize] Using highest resolution {best['width']}x{best['height']} @ {best['fps']}fps ({best['pix_fmt']})")
    return best

def normalize_videos(videos: List[Path], output_dir: Path) -> List[Path]:
    """Convert all videos to same resolution/fps/pix_fmt for safe concat."""
    best = find_highest_quality(videos)
    norm_videos = []
    for v in videos:
        out = output_dir / f"{v.stem}_norm.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(v),
            "-vf", f"scale={best['width']}:{best['height']}:flags=lanczos,fps={best['fps']}",
            "-pix_fmt", best["pix_fmt"],
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "14",
            "-c:a", "aac",
            "-b:a", "192k",
            str(out),
        ]
        print(f"[normalize] Converting {v.name} → {out.name}")
        subprocess.run(cmd, check=True)
        norm_videos.append(out)
    return norm_videos


# ==========================
# 🎞️ Concat Videos
# ==========================
def concat_videos(videos: List[Path], output: Path):
    """Concatenate normalized videos (same resolution)."""
    list_file = output.with_suffix(".txt")
    with list_file.open("w", encoding="utf-8") as f:
        for v in videos:
            f.write(f"file '{v.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c:v", "copy",
        "-c:a", "copy",
        str(output),
    ]
    print(f"[concat] Merging {len(videos)} videos → {output}")
    subprocess.run(cmd, check=True)
    print(f"[concat] ✅ Output: {output}")


# ==========================
# 🔠 Burn Subtitles Function
# ==========================
FONT_PATH = "./assets/microhei.ttc"

def burn_subtitles(input_video: Path, input_srt: Path, output_video: Path) -> bool:
    """Burn subtitles into a video using FFmpeg."""
    font_path = Path(FONT_PATH).resolve()
    if not font_path.exists():
        print(f"[burn] ⚠️ Font not found: {font_path}")
        return False

    subtitles_filter = (
        f"subtitles='{input_srt}':"
        f"force_style='FontName={font_path.stem},FontSize=21,"
        f"PrimaryColour=&Hffffff&,OutlineColour=&H000000&,BorderStyle=1,"
        f"Outline=2,Shadow=0,MarginV=50,Alignment=2'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vf", subtitles_filter,
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "14",
        "-pix_fmt", "yuv444p",
        "-c:a", "copy",
        str(output_video),
    ]

    print(f"[burn] 🔥 Embedding subtitles into video ...")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("[burn] ❌ ffmpeg failed:")
        print(proc.stderr[-400:])
        return False

    print(f"[burn] ✅ Output video: {output_video}")
    return True


# ==========================
# 🧩 Pipeline Entrypoint
# ==========================
def run_combine_pipeline(project_dir: Path, output_name: str, burn_font: bool = False):
    """
    Combine L*.srt + muxed.mp4 → burned subtitle video
    """
    # ---- Combine SRT ----
    subtitles_dir = project_dir / "subtitles"
    output_srt = project_dir / f"{output_name}_full.srt"
    srt_files = sorted(subtitles_dir.glob("L*.srt"), key=lambda p: int(re.search(r"L(\d+)", p.stem).group(1)))
    if not srt_files:
        print(f"❌ No SRT files found under {subtitles_dir}")
        return

    print(f"[combine] Found {len(srt_files)} subtitles")
    combine_srt_files(srt_files, output_srt)

    # ---- Skip re-normalize & concat ----
    muxed_video = project_dir / f"{output_name}_final_muxed.mp4"
    if not muxed_video.exists():
        print(f"⚠️ No muxed file found: {muxed_video}")
        return

    # ---- Burn Subtitles ----
    if burn_font:
        output_video = project_dir / f"{output_name}_with_subs.mp4"
        burn_subtitles(muxed_video, output_srt, output_video)
    else:
        print(f"[combine] ✅ Subtitles merged only — no burning performed.")



load_dotenv()
PROJECT_NAME = os.getenv("PROJECT_NAME")

if __name__ == "__main__":
    project_dir = Path(f"project/{PROJECT_NAME}")
    output_name = PROJECT_NAME
    run_combine_pipeline(project_dir, output_name, burn_font=True)
