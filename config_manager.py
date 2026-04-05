"""Read and write config for AI settings.

On Linux (Render) the config file lives under /tmp.
On Windows (local dev) it lives next to the source.
Environment variables always override file values.
"""

from __future__ import annotations

import json
import os
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))

if os.name == "nt":
    CONFIG_PATH = os.path.join(_HERE, "config.json")
else:
    os.makedirs("/tmp/clippers", exist_ok=True)
    CONFIG_PATH = "/tmp/clippers/config.json"

DEFAULTS: dict[str, Any] = {
    "groq_api_key": "",
    "model": "llama-3.3-70b-versatile",
    "num_clips": 8,
    "clip_duration_min": 15,
    "clip_duration_max": 25,
    "caption_style": "neon",
    "whisper_model": "whisper-large-v3",
    "auto_captions": True,
    "output_format": "vertical",
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
