"""Generate animated word-by-word captions (ASS subtitles) and burn them into video.

Supports both original aspect ratio and vertical 9:16 (Reels/Shorts/TikTok).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


CAPTION_STYLES = {
    "neon": {
        "font": "Arial",
        "fontsize": 20,
        "primary": "&H00FFFFFF",
        "highlight": "&H0000D4FF",    # bright cyan (BGR)
        "outline": "&H00000000",
        "bold": 1,
        "outline_width": 3,
        "shadow": 0,
    },
    "classic": {
        "font": "Arial",
        "fontsize": 18,
        "primary": "&H00FFFFFF",
        "highlight": "&H0000FFFF",    # yellow
        "outline": "&H00000000",
        "bold": 1,
        "outline_width": 2,
        "shadow": 1,
    },
    "bold": {
        "font": "Arial",
        "fontsize": 24,
        "primary": "&H00FFFFFF",
        "highlight": "&H002D75FF",    # hot pink (BGR)
        "outline": "&H00000000",
        "bold": 1,
        "outline_width": 4,
        "shadow": 2,
    },
    "minimal": {
        "font": "Arial",
        "fontsize": 16,
        "primary": "&H00FFFFFF",
        "highlight": "&H0000FF00",    # green
        "outline": "&H80000000",
        "bold": 0,
        "outline_width": 1,
        "shadow": 0,
    },
}


@dataclass
class CaptionResult:
    ok: bool
    output_path: str = ""
    error: Optional[str] = None


def _ts(seconds: float) -> str:
    """Convert seconds to ASS timestamp H:MM:SS.CC."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _group_words_into_lines(words: list[dict], max_words: int = 4) -> list[list[dict]]:
    """Split word list into display lines (shorter for vertical video)."""
    lines: list[list[dict]] = []
    current: list[dict] = []
    for w in words:
        current.append(w)
        if len(current) >= max_words:
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return lines


def generate_ass(
    words: list[dict],
    style_name: str = "neon",
    video_width: int = 1080,
    video_height: int = 1920,
) -> str:
    """Build an ASS subtitle string with karaoke-style word highlighting."""
    style = CAPTION_STYLES.get(style_name, CAPTION_STYLES["neon"])
    lines = _group_words_into_lines(words)

    fs = style["fontsize"]
    if video_width >= 1080:
        fs = int(fs * 1.4)

    margin_v = int(video_height * 0.35)

    header = f"""[Script Info]
Title: Clippers Captions
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['font']},{fs},{style['primary']},&H000000FF,{style['outline']},&H80000000,{style['bold']},0,0,0,100,100,1,0,1,{style['outline_width']},{style['shadow']},2,20,20,{margin_v},1
Style: Highlight,{style['font']},{fs},{style['highlight']},&H000000FF,{style['outline']},&H80000000,{style['bold']},0,0,0,100,100,1,0,1,{style['outline_width']},{style['shadow']},2,20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []

    for line_words in lines:
        if not line_words:
            continue
        line_start = line_words[0]["start"]
        line_end = line_words[-1]["end"]

        base_text_parts: list[str] = []
        for w in line_words:
            base_text_parts.append(w["word"])
        events.append(
            f"Dialogue: 0,{_ts(line_start)},{_ts(line_end)},Default,,0,0,0,,{' '.join(base_text_parts)}"
        )

        karaoke_text = ""
        for i, w in enumerate(line_words):
            dur_cs = max(1, int((w["end"] - w["start"]) * 100))
            word = w["word"]
            if i > 0:
                karaoke_text += " "
            karaoke_text += f"{{\\kf{dur_cs}}}{word}"

        events.append(
            f"Dialogue: 1,{_ts(line_start)},{_ts(line_end)},Highlight,,0,0,0,,{karaoke_text}"
        )

    return header + "\n".join(events) + "\n"


def convert_to_vertical(input_path: str, output_path: str) -> Optional[str]:
    """Convert video to 9:16 vertical format (1080x1920) using FFmpeg."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return None

    cmd = [
        ff, "-y", "-i", input_path,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
        "-c:v", "libx264", "-crf", "23", "-preset", "fast", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        output_path,
    ]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if r.returncode == 0 and os.path.isfile(output_path):
            return output_path
    except Exception:
        pass
    return None


def burn_captions(
    video_path: str,
    output_path: str,
    words: list[dict],
    style_name: str = "neon",
    vertical: bool = True,
) -> CaptionResult:
    """Generate ASS subtitles and burn them into the video using FFmpeg.

    If vertical=True, also converts to 9:16 format.
    """
    if not os.path.isfile(video_path):
        return CaptionResult(ok=False, error="Video file not found.")

    ff = shutil.which("ffmpeg")
    if not ff:
        return CaptionResult(ok=False, error="FFmpeg not found.")

    if vertical:
        w, h = 1080, 1920
    else:
        w, h = 1920, 1080

    ass_content = generate_ass(words, style_name, video_width=w, video_height=h)

    ass_path = output_path + ".tmp_captions.ass"
    try:
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        escaped = ass_path.replace("\\", "/").replace(":", "\\:")

        if vertical:
            vf = (
                f"scale=1080:1920:force_original_aspect_ratio=decrease,"
                f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
                f"ass='{escaped}'"
            )
        else:
            vf = f"ass='{escaped}'"

        cmd = [
            ff, "-y", "-i", video_path,
            "-vf", vf,
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]

        r = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()[:2000] or f"exit {r.returncode}"
            return CaptionResult(ok=False, error=err)

        return CaptionResult(ok=True, output_path=output_path)

    except Exception as e:
        return CaptionResult(ok=False, error=str(e))
    finally:
        if os.path.isfile(ass_path):
            try:
                os.remove(ass_path)
            except OSError:
                pass
