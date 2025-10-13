# videogen/router/decider.py
from __future__ import annotations
from typing import Optional
from videogen.llm_engine import get_engine

def decide_generation_method(
    text: str,
    topic: str,
    context: Optional[str] = None,
) -> str:
    """
    调用 LLM，判断该台词应使用哪种生成方式：
    - react_animation
    - text_to_image
    - subtitle_only
    """

    engine = get_engine()

    # Prompt 模板写在这里，而不是 LLMEngine
    system_prompt = (
        "You are a smart video director assistant. "
        "Your job is to decide which rendering method best fits a given line of script.\n"
        "Possible options:\n"
        "1. react_animation — for abstract, explanatory, or dynamic visual scenes.\n"
        "2. text_to_image — for descriptive or cinematic imagery scenes.\n"
        "3. subtitle_only — for narrative or conversational lines where visuals are not needed.\n"
        "Respond with only one of the three options above.\n"
    )

    user_prompt = (
        f"Video topic: {topic}\n\n"
        f"Line: {text}\n"
    )

    if context:
        user_prompt += f"\nContext: {context}\n"

    user_prompt += "\nWhich rendering method should be used? Reply with one keyword only."

    res = engine.chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=20,
    )

    method = res["content"].strip().lower()
    # normalize output
    if "react" in method:
        return "react_animation"
    elif "image" in method or "picture" in method:
        return "text_to_image"
    else:
        return "subtitle_only"
