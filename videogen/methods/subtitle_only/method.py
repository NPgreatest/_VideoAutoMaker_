from __future__ import annotations
import subprocess, textwrap
from pathlib import Path
from typing import Dict, Any
from ..base import BaseMethod
from ..registry import register_method


@register_method
class SubtitleOnlyMethod(BaseMethod):
    """
    subtitle_only method:
    使用 ffmpeg 生成纯色背景 + 居中字幕的视频。
    适用于旁白、引语、叙事类台词。
    """

    NAME = "subtitle_only"
    OUTPUT_KIND = "video"

    DEFAULT_W = 1280
    DEFAULT_H = 720
    DEFAULT_SEC = 4.0
    FONT_PATH = "./assets/microhei.ttc"   # 中文字体（文泉驿微米黑）

    def run(
        self,
        *,
        prompt: str,
        project: str,
        target_name: str,
        text: str,
        workdir: Path,
        duration_ms: int | None = None,
    ) -> Dict[str, Any]:
        # === 路径设置 ===
        out_dir = workdir / "project" / project
        out_dir.mkdir(parents=True, exist_ok=True)
        out_mp4 = out_dir / f"{target_name}.mp4"

        # === 基础参数 ===
        width = self.DEFAULT_W
        height = self.DEFAULT_H
        duration_sec = (duration_ms or int(self.DEFAULT_SEC * 1000)) / 1000.0
        font_size = 46
        font_color = "white"
        bg_color = "black"
        font_path = Path(self.FONT_PATH).resolve()

        if not font_path.exists():
            return {
                "ok": False,
                "artifacts": [],
                "meta": {},
                "error": f"Font not found: {font_path}",
            }

        # === 文本处理 ===
        # 自动换行防止太长溢出
        safe_text = textwrap.fill(text.strip(), width=28)
        # 转义特殊字符
        escaped = safe_text.replace("'", r"\'").replace(":", "\\:")

        # === FFmpeg filter ===
        # 控制文本宽度限制 + 留白区域
        max_text_w_ratio = 0.7  # 文本最多占屏幕70%
        drawtext_filter = (
            f"drawtext=fontfile='{font_path}':"
            f"text='{escaped}':"
            f"fontcolor={font_color}:fontsize={font_size}:"
            f"x=(w*{(1 - max_text_w_ratio) / 2})+(w*{max_text_w_ratio}-text_w)/2:"
            f"y=(h-text_h)/2:"
            f"box=0"
        )

        # === FFmpeg 命令 ===
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", f"color=c={bg_color}:s={width}x{height}:d={duration_sec}",
            "-vf", drawtext_filter,
            "-r", "30",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out_mp4),
        ]

        # === 执行 ===
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="ignore")[-500:]
            return {
                "ok": False,
                "artifacts": [],
                "meta": {},
                "error": f"ffmpeg failed: {err}",
            }

        return {
            "ok": True,
            "artifacts": [str(out_mp4)],
            "meta": {
                "mode": "subtitle_only",
                "text": text,
                "duration_sec": duration_sec,
                "font": str(font_path),
                "output_path": str(out_mp4),
            },
            "error": None,
        }
