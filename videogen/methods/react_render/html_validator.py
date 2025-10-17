# html_validator.py
from __future__ import annotations
from typing import Any

def validate_html(engine: Any, html_text: str) -> bool:
    """
    Ask LLM to validate if HTML is runnable for React video generation.
    Returns True if it seems valid (single <html>, <script type="text/babel">, etc.)
    """
    validate_prompt = (
        "You are a strict validator. "
        "I will give you a full HTML page that should display a short React 18 UMD + Babel animation. "
        "If it looks valid enough to render (no syntax errors, no nested <html>, "
        "includes at least one <script type='text/babel'> with ReactDOM.render or createRoot), "
        "respond strictly with 'True'. "
        "If it seems broken, missing scripts, or malformed, respond strictly with 'False'. "
        "Output only 'True' or 'False'."
    )

    try:
        ans = engine.ask_text(f"{validate_prompt}\n\nHTML:\n{html_text[:6000]}")
        ans = ans.strip().lower()
        return "true" in ans and "false" not in ans
    except Exception as e:
        print(f"[Validator] Validation error: {e}")
        return False
