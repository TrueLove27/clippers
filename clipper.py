"""Clip local video files with FFmpeg."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class ClipResult:
    ok: bool
    output_path: str
    error: Optional[str] = None


def ffmpeg_path() -> Optional[str]:
    return shutil.which("ffmpeg")


def clip_video(
    input_path: str,
    output_path: str,
    start: str,
    end: Optional[str] = None,
    duration: Optional[str] = None,
) -> ClipResult:
    """
    Extract a segment using FFmpeg.
    start/end/duration: FFmpeg time format (e.g. 00:01:30, 90, 1:30).
    Provide either end OR duration, not both (if both, end wins).
    """
    if not os.path.isfile(input_path):
        return ClipResult(False, output_path, error="Input file not found")
    ff = ffmpeg_path()
    if not ff:
        return ClipResult(
            False,
            output_path,
            error="FFmpeg not found. Install FFmpeg and add it to PATH.",
        )
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

    cmd = [
        ff,
        "-y",
        "-ss",
        start.strip(),
        "-i",
        input_path,
    ]
    if end:
        cmd.extend(["-to", end.strip()])
    elif duration:
        cmd.extend(["-t", duration.strip()])
    else:
        return ClipResult(
            False,
            output_path,
            error="Provide end time or duration for the clip.",
        )

    cmd.extend(
        [
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            output_path,
        ]
    )

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
            return ClipResult(False, output_path, error=err[:2000])
        return ClipResult(True, output_path)
    except Exception as e:
        return ClipResult(False, output_path, error=str(e))
