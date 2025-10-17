#!/usr/bin/env python3
from __future__ import annotations
import re, subprocess
from pathlib import Path
from typing import List

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
    """
    Combine multiple .srt files into one continuous timeline.
    Automatically adjusts timestamps cumulatively.
    """
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

        total_offset += local_end  # accumulate global offset

    with output_file.open("w", encoding="utf-8") as f:
        for idx, start, end, text in all_entries:
            f.write(f"{idx}\n{start} --> {end}\n{text}\n\n")

    print(f"✅ [combine] Combined {len(all_entries)} subtitles → {output_file}")


# ==========================
# 🔠 Burn Subtitles Function
# ==========================
FONT_PATH = "./assets/microhei.ttc"

def burn_subtitles(input_video: Path, input_srt: Path, output_video: Path) -> bool:
    """
    Burn subtitles into a video using FFmpeg.
    Uses a clean white font with black outline for readability.
    """
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
        "-crf", "15",
        "-pix_fmt", "yuv444p",
        "-c:a", "copy",
        str(output_video),
    ]

    print(f"[burn] Running FFmpeg command:")
    print(" ".join(cmd))
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
    Combine all L*.srt files in subtitles/ into one .srt file,
    and optionally burn it into the video.
    """
    subtitles_dir = project_dir / "subtitles"
    output_srt = project_dir / f"{output_name}_full.srt"

    srt_files = sorted(
        subtitles_dir.glob("L*.srt"),
        key=lambda p: int(re.search(r"L(\d+)", p.stem).group(1))
    )
    if not srt_files:
        print(f"❌ No SRT files found under {subtitles_dir}")
        return

    print(f"[combine] Found {len(srt_files)} SRTs: {[p.name for p in srt_files]}")
    combine_srt_files(srt_files, output_srt)

    if burn_font:
        input_video = project_dir / f"{output_name}_final_muxed.mp4"
        output_video = project_dir / f"{output_name}_with_subs.mp4"
        if not input_video.exists():
            print(f"[burn] ⚠️ Missing input video: {input_video}")
            return
        burn_subtitles(input_video, output_srt, output_video)
    else:
        print(f"[combine] ✅ Subtitles combined only — no burning performed.")


# ==========================
# 🧠 Manual Run
# ==========================
if __name__ == "__main__":
    project_dir = Path("project/mh370_demo")
    output_name = "mh370_demo"

    # set True to embed subtitles into video
    run_combine_pipeline(project_dir, output_name, burn_font=True)
