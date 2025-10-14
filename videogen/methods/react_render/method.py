from __future__ import annotations
import http.server, socketserver, threading
import json, subprocess, tempfile, re, html, shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any

from videogen.methods.base import BaseMethod
from videogen.methods.registry import register_method
from videogen.llm_engine import get_engine, LLMConfigError
from videogen.utils.js_syntax_checker import check_jsx_syntax  # 语法检查

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_OK = True
except Exception:
    _PLAYWRIGHT_OK = False

HERE = Path(__file__).parent
TEMPLATE_JSX = HERE / "template_jsx.html"  # 极简 JSX 播放模板

REACT_UMD = "https://unpkg.com/react@18/umd/react.production.min.js"
REACTDOM_UMD = "https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"
BABEL_UMD = "https://unpkg.com/@babel/standalone/babel.min.js"

# 语法失败时的最大重试次数（仅针对 LLM 生成的 JSX）
MAX_SYNTAX_RETRIES = 3

def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def _sanitize_jsx(raw: str) -> str:
    """去除 fence/import/export/createRoot/ReactDOM.render，确保 Scene + window.__SCENE__ 存在。"""
    text = (raw or "").strip()
    text = re.sub(r"^```[\s\S]*?\n", "", text)
    text = re.sub(r"\n```$", "", text)
    text = text.replace("```jsx","").replace("```tsx","").replace("```js","").replace("```","")
    lines = []
    for ln in text.splitlines():
        if re.match(r"^\s*(import|export)\b", ln): continue
        if "createRoot(" in ln or "ReactDOM.render" in ln: continue
        lines.append(ln)
    text = "\n".join(lines).strip()

    has_scene = re.search(r"\b(function|const|let)\s+Scene\b", text) is not None
    if not has_scene:
        text += """
function Scene(){
  return (
    <div style={{display:'grid',placeItems:'center',width:'100%',height:'100%',color:'#e7eaf3',fontSize:46}}>
      Scene
    </div>
  );
}
""".strip("\n")
    if "window.__SCENE__" not in text:
        text += "\nwindow.__SCENE__ = Scene;"
    return text

def _build_index_html(title: str, width: int, height: int, jsx: str, duration_sec: float, subtitle: str) -> str:
    """把 JSX 注入模板，生成完整 HTML。"""
    template = TEMPLATE_JSX.read_text(encoding="utf-8")
    return (template
            .replace("{{TITLE}}", html.escape(title))
            .replace("{{WIDTH}}", str(width))
            .replace("{{HEIGHT}}", str(height))
            .replace("{{REACT_UMD}}", REACT_UMD)
            .replace("{{REACTDOM_UMD}}", REACTDOM_UMD)
            .replace("{{BABEL_UMD}}", BABEL_UMD)
            .replace("{{DURATION_MS}}", str(int(max(0.5, duration_sec) * 1000)))
            # .replace("{{SUBTITLE}}", html.escape(subtitle or ""))
            .replace("{{SCENE_BABEL}}", f"<script type=\"text/babel\">\n{jsx}\n</script>")
            )

@contextmanager
def _serve_dir(root_dir: Path):
    Handler = lambda *args, **kw: http.server.SimpleHTTPRequestHandler(*args, directory=str(root_dir), **kw)  # noqa
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as httpd:
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            yield httpd.server_address[1]
        finally:
            httpd.shutdown(); httpd.server_close(); t.join()

def _record_url(page_url: str, out_video: Path, width: int, height: int, duration_ms: int, lead_in_trim_ms: int = 800) -> Path:
    if not _PLAYWRIGHT_OK:
        raise RuntimeError("playwright 未安装：pip install playwright && playwright install chromium")

    out_video.parent.mkdir(parents=True, exist_ok=True)
    tmp_webm = out_video.with_suffix(".webm")

    trim_ms = max(0, int(lead_in_trim_ms))
    trim_sec = trim_ms / 1000.0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": width, "height": height},
            record_video_dir=str(out_video.parent),
            record_video_size={"width": width, "height": height},
            device_scale_factor=2
        )
        page = context.new_page()
        # networkidle 比 load 更晚一点，能减少首帧白屏概率（依然建议配合裁剪）
        page.goto(page_url, wait_until="networkidle")
        try:
            page.wait_for_function("() => window.__PLAY_DONE === true", timeout=duration_ms + 8000)
        except Exception:
            page.wait_for_timeout(duration_ms + 800)
        tmp_path = Path(page.video.path())
        context.close(); browser.close()

    tmp_path.replace(tmp_webm)

    # === 输出 MP4，并裁掉前置空镜 ===
    if _which("ffmpeg") and out_video.suffix.lower() == ".mp4":
        cmd = [
            "ffmpeg", "-y",
            "-i", str(tmp_webm),
            "-ss", f"{trim_sec:.3f}",   # 精确裁掉前 trim_sec 秒
            "-vf", f"scale={width}:{height}:flags=lanczos",
            "-r", "60",
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "16",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-bf", "2",
            "-g", "120",
            "-movflags", "+faststart",
            str(out_video)
        ]
        subprocess.run(cmd, check=True)
        try: tmp_webm.unlink(missing_ok=True)
        except Exception: pass
        return out_video
    else:
        return tmp_webm


@register_method
class ReactRenderMethod(BaseMethod):
    """
    纯 Prompt → JSX → index.html + 录制视频（语法错误自动重试）
    - text: str           （必须，交给 LLM 作为 React 场景的提示）
    - prompt: str         （可选，作为字幕/说明文字）
    - duration_ms: int    （可选，视频时长（毫秒），如 5000/10000；不传则用 DEFAULT_SEC）
    输出：
      {workdir}/project/{project}/index.html
      {workdir}/project/{project}/{target_name}.mp4  (若无 ffmpeg 则为 .webm)
    """
    NAME = "react_animation"
    OUTPUT_KIND = "video"

    DEFAULT_W = 1280
    DEFAULT_H = 720
    DEFAULT_SEC = 4.0  # 默认 4s

    def run(
        self,
        *,
        prompt: str,
        project: str,
        target_name: str,
        text: str,
        workdir: Path,
        duration_ms: int | None = None,   # ← 新增
    ) -> Dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            return {"ok": False, "artifacts": [], "meta": {}, "error": "text 必须是非空字符串（作为 LLM 提示）"}

        out_dir = workdir / "project" / project
        out_dir.mkdir(parents=True, exist_ok=True)
        out_html = out_dir / "index.html"
        out_video = out_dir / f"{target_name}.mp4"

        width = self.DEFAULT_W
        height = self.DEFAULT_H

        # 若外部传入毫秒数则使用；否则使用默认秒数
        if duration_ms is not None:
            duration_ms_final = int(duration_ms)
            duration_sec = max(0.5, duration_ms_final / 1000.0)
        else:
            duration_sec = self.DEFAULT_SEC
            duration_ms_final = int(duration_sec * 1000)

        subtitle = prompt or ""   # 用 prompt 当字幕，纯可选

        # 0) 拿到 LLM 引擎
        try:
            engine = get_engine()
        except LLMConfigError as e:
            return {"ok": False, "artifacts": [], "meta": {}, "error": f"LLM 配置错误: {e}"}

        # 1) 生成 JSX，并在语法失败时重试
        last_err = ""
        last_tool = None
        jsx_clean = None

        for attempt in range(1, MAX_SYNTAX_RETRIES + 1):
            try:
                jsx_raw = engine.gen_react_jsx(text, width=width, height=height)
            except Exception as e:
                last_err = f"LLM 生成失败: {e}"
                print(f'{attempt} attempt failed, {e}')
                if attempt < MAX_SYNTAX_RETRIES:
                    continue
                else:
                    return {"ok": False, "artifacts": [], "meta": {"attempts": attempt}, "error": last_err}

            jsx_candidate = _sanitize_jsx(jsx_raw)
            ok_syntax, msg_syntax, tool = check_jsx_syntax(jsx_candidate, filename_hint="scene.jsx")
            last_tool = tool
            if ok_syntax:
                jsx_clean = jsx_candidate
                break
            else:
                last_err = f"JSX 语法检查失败（{tool}）：{msg_syntax}"
                print(f'{attempt} attempt {last_err}')
                if attempt < MAX_SYNTAX_RETRIES:
                    continue
                else:
                    return {"ok": False, "artifacts": [], "meta": {"attempts": attempt, "syntax_tool": tool}, "error": last_err}

        # 2) 组装 index.html
        html_text = _build_index_html(
            title=f"{project}:{target_name}",
            width=width, height=height,
            jsx=jsx_clean,                 # type: ignore[arg-type]
            duration_sec=duration_sec,
            subtitle=subtitle
        )
        out_html.write_text(html_text, encoding="utf-8")

        # 3) 起本地服并录制
        try:
            with tempfile.TemporaryDirectory(prefix="react_prompt_") as td:
                tmp_dir = Path(td)
                tmp_index = tmp_dir / "index.html"
                tmp_index.write_text(html_text, encoding="utf-8")
                with _serve_dir(tmp_dir) as port:
                    url = f"http://127.0.0.1:{port}/index.html"
                    final_path = _record_url(
                        url, out_video, width, height,
                        duration_ms_final,                 # ← 使用最终毫秒数
                    )
        except subprocess.CalledProcessError as e:
            return {"ok": False, "artifacts": [str(out_html)], "meta": {}, "error": f"ffmpeg 失败: {e}"}
        except Exception as e:
            return {"ok": False, "artifacts": [str(out_html)], "meta": {}, "error": str(e)}

        return {
            "ok": True,
            "artifacts": [str(out_html), str(final_path)],
            "meta": {
                "mode": "jsx-prompt",
                "width": width, "height": height,
                "durationSec": duration_sec,
                "durationMs": duration_ms_final,      # ← 回传毫秒
                "html": str(out_html),
                "video": str(final_path),
                "attempts": attempt,                  # 实际尝试次数
                "syntax_tool": last_tool,             # 使用的语法检查器
            },
            "error": None
        }
