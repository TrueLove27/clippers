"""Read and write config for AI settings.

On Render / production the config file lives under /tmp (ephemeral).
Environment variables always override file values.
"""

from __future__ import annotations

import json
import os
from typing import Any

_ON_RENDER = bool(os.environ.get("RENDER"))

if _ON_RENDER:
    CONFIG_PATH = "/tmp/clippers_config.json"
else:
    CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS: dict[str, Any] = {
    "groq_api_key": "",
    "model": "llama-3.3-70b-versatile",
    "num_clips": 5,
    "clip_duration_min": 30,
    "clip_duration_max": 90,
    "caption_style": "neon",
    "whisper_model": "large-v3",
}

ENV_MAP = {
    "groq_api_key": "GROQ_API_KEY",
    "model": "GROQ_MODEL",
}


def load() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                stored = json.load(f)
            cfg.update(stored)
        except (json.JSONDecodeError, OSError):
            pass
    for key, env_var in ENV_MAP.items():
        val = os.environ.get(env_var)
        if val:
            cfg[key] = val
    return cfg


def save(updates: dict[str, Any]) -> dict[str, Any]:
    cfg = load()
    cfg.update(updates)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass
    return cfg


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)
