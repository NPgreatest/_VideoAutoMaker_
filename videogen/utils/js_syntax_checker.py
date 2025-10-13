# videogen/utils/js_syntax_checker.py
from __future__ import annotations
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Tuple

# Public API ==================================================================

def check_jsx_syntax(
    jsx_text: str,
    *,
    filename_hint: str = "scene.jsx",
    timeout_sec: float = 6.0,
) -> Tuple[bool, str, str]:
    """
    检查 JSX/TSX 语法是否可被工具解析。
    返回: (ok, message, tool_used)
      - ok: True 表示语法通过
      - message: 诊断/错误信息（尽量简短）
      - tool_used: "esbuild" | "fallback"
    说明:
      1) 首选使用 esbuild (通过 `npx esbuild ...`) 做 parse/bundle 到 /dev/null。
      2) 如果环境没有 esbuild，则使用简易退化检查（括号/大括号/方括号配对 + window.__SCENE__ 存在性）。
         此模式不保证100%准确，只用于兜底。
    """
    jsx = (jsx_text or "").strip()
    if not jsx:
        return False, "JSX 为空", "fallback"

    # 先试 esbuild
    if _has_cmd("npx"):
        ok, msg = _check_with_esbuild(jsx, filename_hint=filename_hint, timeout_sec=timeout_sec)
        if ok is not None:  # None 表示 esbuild 不可用/失败为环境问题
            return ok, msg, "esbuild"

    # 退化检查（不依赖外部工具）
    ok_fallback, msg_fallback = _fallback_bracket_check(jsx)
    return ok_fallback, msg_fallback, "fallback"


# Internal helpers ============================================================

def _has_cmd(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def _check_with_esbuild(
    jsx_text: str,
    *,
    filename_hint: str,
    timeout_sec: float,
) -> tuple[bool | None, str]:
    import subprocess, tempfile
    from pathlib import Path

    try:
        # 临时输入文件（带 .jsx/.tsx 后缀）
        with tempfile.NamedTemporaryFile("w+", suffix=_suffix_from_hint(filename_hint), delete=False) as f_in:
            in_path = Path(f_in.name)
            f_in.write(jsx_text)
            f_in.flush()

        # 临时输出 .js
        with tempfile.NamedTemporaryFile("w+", suffix=".js", delete=False) as f_out:
            out_path = Path(f_out.name)

        args = [
            "npx", "--yes", "esbuild",
            str(in_path),
            # 不要 --loader=jsx/tsx（这会触发你遇到的报错）
            "--jsx=transform",
            "--jsx-factory=React.createElement",
            "--jsx-fragment=React.Fragment",
            "--platform=browser",
            "--target=es2018",
            "--log-level=error",
            f"--outfile={out_path}",
        ]

        try:
            res = subprocess.run(args, capture_output=True, text=True, timeout=timeout_sec)
        finally:
            try: in_path.unlink(missing_ok=True)
            except Exception: pass
            try: out_path.unlink(missing_ok=True)
            except Exception: pass

        if res.returncode == 0:
            return True, "ok"

        err = (res.stderr or res.stdout or "").strip()
        err_first_line = err.splitlines()[0] if err else "esbuild 语法错误"
        return False, err_first_line

    except FileNotFoundError:
        return None, "npx/esbuild 不可用"
    except subprocess.TimeoutExpired:
        return None, "esbuild 语法检查超时"
    except Exception as e:
        return None, f"esbuild 调用异常: {e}"




def _suffix_from_hint(hint: str) -> str:
    hint = (hint or "").lower()
    if hint.endswith(".tsx"):
        return ".tsx"
    if hint.endswith(".jsx"):
        return ".jsx"
    return ".jsx"

def _fallback_bracket_check(jsx_text: str) -> tuple[bool, str]:
    """
    简易退化检查：配对括号 & 必要标识。
    注意：非严格解析，仅用于 esbuild 不可用时的早期筛查。
    """
    s = jsx_text

    # 必要标识
    if "window.__SCENE__" not in s:
        return False, "缺少 window.__SCENE__ 绑定"

    # 配对括号快速检查
    pairs = {"(": ")", "[": "]", "{": "}"}
    openers = set(pairs.keys())
    closers = set(pairs.values())
    stack: list[str] = []

    for ch in s:
        if ch in openers:
            stack.append(ch)
        elif ch in closers:
            if not stack:
                return False, "括号配对错误（多余的右括号）"
            op = stack.pop()
            if pairs[op] != ch:
                return False, "括号配对错误（类型不匹配）"

    if stack:
        return False, "括号配对错误（缺少右括号）"

    # 粗糙通过
    return True, "ok(降级)"


# Convenience =================================================================

def assert_jsx_syntax_ok(jsx_text: str, *, filename_hint: str = "scene.jsx", timeout_sec: float = 6.0) -> None:
    """若语法不通过则抛出 ValueError（给调用方快速使用）。"""
    ok, msg, tool = check_jsx_syntax(jsx_text, filename_hint=filename_hint, timeout_sec=timeout_sec)
    if not ok:
        raise ValueError(f"JSX 语法检查失败（{tool}）：{msg}")
