#!/usr/bin/env python3
from __future__ import annotations
import os, re, json, shlex, subprocess
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
    print(f"[ffmpeg] Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("[ffmpeg] ❌ Failed:")
        print(proc.stderr[-400:])
        return False
    return True

# ==========================================
# 🔊 Merge WAVs (safe re-encode)
# ==========================================
def _concat_wavs_with_ffmpeg(wav_paths: List[Path], out_path: Path) -> bool:
    if not wav_paths:
        print("[concat] ⚠️ No wavs to merge.")
        return False
    lst = out_path.with_suffix(".txt")
    lst.write_text("\n".join(f"file '{p.resolve()}'" for p in wav_paths), encoding="utf-8")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(lst),
        "-ac", "2", "-ar", "44100",
        "-c:a", "pcm_s16le",  # 无损 PCM
        str(out_path),
    ]
    ok = _run_ffmpeg(cmd)
    lst.unlink(missing_ok=True)
    if ok:
        print(f"[concat] ✅ Merged WAV → {out_path.name}")
    return ok

# ==========================================
# 🎞️ Safe concat videos (with re-encode & PTS fix)
# ==========================================
def _concat_videos_with_ffmpeg(video_paths: List[Path], out_path: Path) -> bool:
    """Re-encode concat to fix PTS drift and ensure perfect sync."""
    if not video_paths:
        print("[concat] ⚠️ No videos to merge.")
        return False

    lst = out_path.with_suffix(".txt")
    lst.write_text("\n".join(f"file '{p.resolve()}'" for p in video_paths), encoding="utf-8")

    # 🧠 自动检测平均帧率
    fps_values = []
    for v in video_paths:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", str(v)],
            capture_output=True, text=True)
        fps_raw = res.stdout.strip()
        if fps_raw:
            try:
                num, den = fps_raw.split('/')
                fps_values.append(float(num) / float(den))
            except Exception:
                pass
    avg_fps = round(sum(fps_values) / len(fps_values)) if fps_values else 30
    print(f"[concat] 🧩 Detected average FPS: {avg_fps}")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(lst),
        "-vf", f"fps={avg_fps},format=yuv420p",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-c:a", "aac", "-ar", "44100", "-b:a", "192k",
        "-fflags", "+genpts",  # 🔧 重建 PTS
        "-avoid_negative_ts", "make_zero",
        "-shortest", "-async", "1",
        str(out_path),
    ]
    ok = _run_ffmpeg(cmd)
    lst.unlink(missing_ok=True)
    if ok:
        print(f"[concat] ✅ Final video merged safely → {out_path.name}")
    return ok

# ==========================================
# 🎧 Mux Audio + Video
# ==========================================
def _mux_audio_video(video_path: Path, audio_path: Path, out_path: Path) -> bool:
    if not video_path.exists() or not audio_path.exists():
        print("[mux] ⚠️ Missing video/audio for mux.")
        return False
    tmp_aac = audio_path.with_suffix(".aac")
    cmd_audio = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-ac", "2", "-ar", "44100",
        "-c:a", "aac", "-b:a", "192k",
        str(tmp_aac)
    ]
    print(f"[mux] 🔊 Converting audio → AAC ...")
    if not _run_ffmpeg(cmd_audio):
        return False

    cmd_mux = [
        "ffmpeg", "-y",
        "-i", str(video_path), "-i", str(tmp_aac),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "copy",
        "-shortest", "-async", "1",
        str(out_path),
    ]
    ok = _run_ffmpeg(cmd_mux)
    tmp_aac.unlink(missing_ok=True)
    if ok:
        print(f"[mux] ✅ Muxed output → {out_path.name}")
    return ok

# ==========================================
# 🔠 Subtitle merge + burn
# ==========================================
def parse_srt_time(time_str: str) -> float:
    h, m, s_ms = time_str.split(":")
    s, ms = s_ms.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def combine_srt_files(input_files: List[Path], output_file: Path) -> None:
    print(f"[combine] Merging {len(input_files)} SRT files → {output_file.name}")
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
            m = re.match(r"(\d\d:\d\d:\d\d,\d{3}) --> (\d\d:\d\d:\d\d,\d{3})", lines[1])
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
    print(f"[combine] ✅ Combined subtitles → {output_file.name}")

def burn_subtitles(input_video: Path, input_srt: Path, output_video: Path) -> bool:
    FONT_PATH = "./assets/microhei.ttc"
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
        "-c:v", "libx264", "-preset", "slow", "-crf", "14",
        "-pix_fmt", "yuv444p", "-c:a", "copy",
        str(output_video),
    ]
    print(f"[burn] 🔥 Burning subtitles ...")
    return _run_ffmpeg(cmd)

# ==========================================
# 🧩 Main
# ==========================================
def concat_project_media(json_path: Path, workdir: Path) -> None:
    print(f"🎬 Starting concat for {json_path}")
    raw = read_json(json_path)
    project_name = raw.get("project")
    project_dir = workdir / "project" / project_name

    blocks = [from_dict(ScriptBlock, b) for b in raw.get("script", [])]
    audio_files, video_files = [], []

    for b in blocks:
        if b.audioGeneration and b.audioGeneration.ok:
            merged_audio = b.audioGeneration.meta.get("merged")
            if merged_audio:
                audio_files.append(project_dir / merged_audio)
        if b.generation and b.generation.ok:
            video_meta = b.generation.meta
            video_file = video_meta.get("video") or video_meta.get("output_path")
            if video_file:
                p = Path(video_file)
                if p.is_absolute():
                    video_files.append(p)
                elif str(p).startswith("project/"):
                    video_files.append(workdir / p)
                else:
                    video_files.append(project_dir / p)

    # 🧩 逐段 mux（确保 clip 对齐）
    muxed_clips = []
    for i, (a, v) in enumerate(zip(audio_files, video_files)):
        out = project_dir / f"L{i+1}_muxed.mp4"
        if _mux_audio_video(v, a, out):
            muxed_clips.append(out)

    # 🧱 合并所有 muxed 视频
    final_muxed = project_dir / f"{project_name}_final_muxed.mp4"
    if _concat_videos_with_ffmpeg(muxed_clips, final_muxed):
        raw["final_muxed"] = str(final_muxed.relative_to(workdir))

    # 额外输出纯音频和纯视频（方便调试）
    final_audio = project_dir / f"{project_name}_final.wav"
    final_video = project_dir / f"{project_name}_final.mp4"
    _concat_wavs_with_ffmpeg(audio_files, final_audio)
    _concat_videos_with_ffmpeg(video_files, final_video)
    raw["final_audio"] = str(final_audio.relative_to(workdir))
    raw["final_video"] = str(final_video.relative_to(workdir))

    # 🈶 合并并烧录字幕
    subtitles_dir = project_dir / "subtitles"
    srt_files = sorted(subtitles_dir.glob("L*.srt"), key=lambda p: int(re.search(r"L(\d+)", p.stem).group(1)))
    if srt_files:
        output_srt = project_dir / f"{project_name}_full.srt"
        combine_srt_files(srt_files, output_srt)
        burned_video = project_dir / f"{project_name}_with_subs.mp4"
        if burn_subtitles(final_muxed, output_srt, burned_video):
            raw["final_burned"] = str(burned_video.relative_to(workdir))
            print(f"✅ Burned subtitles video → {burned_video.name}")
    else:
        print("⚠️ No subtitles found to merge.")

    write_json(json_path, raw)
    print(f"✅ All concat steps complete for {project_name}")

# ==========================================
# 🚀 Entrypoint
# ==========================================
load_dotenv()
PROJECT_NAME = os.getenv("PROJECT_NAME")

if __name__ == "__main__":
    concat_project_media(
        Path(f"./project/{PROJECT_NAME}/{PROJECT_NAME}.json"),
        Path(".")
    )
