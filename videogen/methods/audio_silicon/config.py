#!/usr/bin/env python3
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Dict, Any
import requests
from dotenv import load_dotenv

# ========== 环境加载 ==========
load_dotenv()
SILICON_API_KEY = os.getenv("SILICONFLOW_API_TOKEN")
UPLOAD_URL = "https://api.siliconflow.cn/v1/uploads/audio/voice"
MODEL_NAME = "FunAudioLLM/CosyVoice2-0.5B"

# ========== 路径定义 ==========
# 从当前文件位置向上找到项目根目录，然后定位到 config 目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "voice_config.json"
ASSET_DIR = PROJECT_ROOT / "assets" / "voices"

# ========== JSON 操作 ==========
def _load_config() -> Dict[str, Any]:
    """读取本地 voice_config.json"""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[VoiceConfig] ⚠️ Failed to read config: {e}")
    return {}


def _save_config(cfg: Dict[str, Any]) -> None:
    """保存配置文件"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# ========== 上传语音 ==========
def _upload_voice(character: str, file_path: Path, text: str) -> str:
    """上传参考音频，返回 URI"""
    headers = {"Authorization": f"Bearer {SILICON_API_KEY}"}
    files = {"file": open(file_path, "rb")}
    payload = {
        "model": MODEL_NAME,
        "customName": character,
        "text": text,
    }

    try:
        print(f"[VoiceConfig] ⬆️ Uploading '{character}' voice from {file_path.name} ...")
        resp = requests.post(UPLOAD_URL, data=payload, files=files, headers=headers, timeout=60)
        if resp.status_code == 200:
            uri = resp.json().get("uri", "")
            if uri:
                print(f"[VoiceConfig] ✅ Uploaded '{character}' → {uri}")
                return uri
        else:
            print(f"[VoiceConfig] ❌ Upload failed ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        print(f"[VoiceConfig] ❌ Exception while uploading: {e}")
    finally:
        files["file"].close()
    return ""


# ========== 核心函数 ==========
def ensure_voice_uri(character: str | None) -> str:
    """
    返回角色名与 URI：
    - 如果传入角色名为空，则选第一个作为默认角色；
    - 若本地有缓存则直接返回；
    - 若无则上传后保存。
    """
    cfg = _load_config()

    # 🔹 若没有角色配置文件
    if not cfg:
        print("[VoiceConfig] ⚠️ No voice_config.json found or empty.")
        return ""

    # 🔹 自动选择第一个角色作为 default
    if not character:
        character = list(cfg.keys())[0]
        print(f"[VoiceConfig] 🟢 Using default character: {character}")

    # 🔹 优先从缓存返回 URI
    entry = cfg.get(character)
    if entry and entry.get("uri"):
        print(f"[VoiceConfig] Using cached URI for '{character}': {entry['uri']}")
        return entry["uri"]

    # 🔹 匹配本地文件（大小写不敏感）
    file_path = ASSET_DIR / f"{character}.wav"
    if not file_path.exists():
        matches = [p for p in ASSET_DIR.glob("*.wav") if p.stem.lower() == character.lower()]
        if matches:
            file_path = matches[0]
            print(f"[VoiceConfig] ⚠️ Found file with case-insensitive match: {file_path.name}")
        else:
            print(f"[VoiceConfig] ❌ Missing local file for {character}: {file_path}")
            return ""

    sample_text = entry.get('text')

    # 🔹 上传语音并更新缓存
    uri = _upload_voice(character, file_path, sample_text)
    if uri:
        cfg[character] = {
            "uri": uri,
            "text": sample_text,
            "model": MODEL_NAME,
            "file_path": str(file_path),
        }
        _save_config(cfg)
    return uri


def list_cached_voices() -> Dict[str, str]:
    """列出所有已缓存角色与 URI"""
    cfg = _load_config()
    return {k: v.get("uri", "") for k, v in cfg.items()}


def get_default_character() -> str:
    """返回 voice_config.json 中第一个角色"""
    cfg = _load_config()
    return list(cfg.keys())[0] if cfg else "default"
