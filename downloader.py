"""YouTube (and other) downloads via yt-dlp."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

import yt_dlp


ProgressCallback = Callable[[str, dict], None]


@dataclass
class DownloadResult:
    ok: bool
    url: str
    error: Optional[str] = None
    filepath: Optional[str] = None


def _progress_hook(
    cb: Optional[ProgressCallback], status: dict
) -> None:
    if cb is None:
        return
    if status.get("status") == "downloading":
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        downloaded = status.get("downloaded_bytes") or 0
        if total:
            pct = min(100, int(downloaded * 100 / total))
            cb("downloading", {**status, "percent": pct})
        else:
            cb("downloading", status)
    elif status.get("status") == "finished":
        cb("finished", status)


def download_url(
    url: str,
    out_dir: str,
    *,
    progress: Optional[ProgressCallback] = None,
    merge_format: str = "bestvideo+bestaudio/best",
) -> DownloadResult:
    """Download a single URL into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    opts: dict = {
        "outtmpl": os.path.join(out_dir, "%(title)s [%(id)s].%(ext)s"),
        "merge_output_format": "mp4",
        "format": merge_format,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [lambda s: _progress_hook(progress, s)],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                return DownloadResult(False, url, error="No info returned")
            path = ydl.prepare_filename(info)
            if info.get("_type") == "playlist":
                return DownloadResult(True, url, filepath=out_dir)
            return DownloadResult(True, url, filepath=path)
    except Exception as e:
        return DownloadResult(False, url, error=str(e))


def download_playlist(
    url: str,
    out_dir: str,
    *,
    progress: Optional[ProgressCallback] = None,
) -> DownloadResult:
    os.makedirs(out_dir, exist_ok=True)
    opts: dict = {
        "outtmpl": os.path.join(out_dir, "%(playlist_title)s/%(title)s [%(id)s].%(ext)s"),
        "merge_output_format": "mp4",
        "format": "bestvideo+bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [lambda s: _progress_hook(progress, s)],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        return DownloadResult(True, url, filepath=out_dir)
    except Exception as e:
        return DownloadResult(False, url, error=str(e))
