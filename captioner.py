"""Generate animated word-by-word captions (ASS subtitles) and burn them into video."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


CAPTION_STYLES = {
    "classic": {
        "font": "Arial",
        "fontsize": 22,
        "primary": "&H00FFFFFF",   # white
        "highlight": "&H0000FFFF", # yellow
        "outline": "&H00000000",   # black
        "bold": 1,
        "outline_width": 2,
        "shadow": 1,
    },
    "neon": {
        "font": "Arial",
        "fontsize": 24,
        "primary": "&H00FFFFFF",
        "highlight": "&H00FFD400", # cyan (BGR)
        "outline": "&H00000000",
        "bold": 1,
        "outline_width": 3,
        "shadow": 0,
    },
    "bold": {
        "font": "Arial",
        "fontsize": 28,
        "primary": "&H00FFFFFF",
        "highlight": "&H002D75FF", # pink (BGR)
        "outline": "&H00000000",
        "bold": 1,
        "outline_width": 4,
        "shadow": 2,
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


def _group_words_into_lines(words: list[dict], max_words: int = 6) -> list[list[dict]]:
    """Split word list into display lines."""
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
    video_width: int = 1920,
    video_height: int = 1080,
) -> str:
    """Build an ASS subtitle string with karaoke-style word highlighting."""
    style = CAPTION_STYLES.get(style_name, CAPTION_STYLES["neon"])
    lines = _group_words_into_lines(words)

    header = f"""[Script Info]
Title: Clippers Captions
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['font']},{style['fontsize']},{style['primary']},&H000000FF,{style['outline']},&H80000000,{style['bold']},0,0,0,100,100,0,0,1,{style['outline_width']},{style['shadow']},2,20,20,40,1
Style: Highlight,{style['font']},{style['fontsize']},{style['highlight']},&H000000FF,{style['outline']},&H80000000,{style['bold']},0,0,0,100,100,0,0,1,{style['outline_width']},{style['shadow']},2,20,20,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []

    for line_words in lines:
        if not line_words:
            continue
        line_start = line_words[0]["start"]
        line_end = line_words[-1]["end"]

        text_parts: list[str] = []
        for i, w in enumerate(line_words):
            dur_cs = max(1, int((w["end"] - w["start"]) * 100))
            word_text = w["word"]
            text_parts.append(f"{{\\kf{dur_cs}}}{word_text}")

        ass_text = " ".join(text_parts) if not text_parts else "".join(text_parts)
        # Use highlight style for karaoke fill color
        events.append(
            f"Dialogue: 0,{_ts(line_start)},{_ts(line_end)},Default,,0,0,0,karaoke,{{\\K0}}{' '.join(t.split('}')[-1] if '}' in t else t for t in text_parts)}"
        )

        # Overlay with karaoke timing for the highlight effect
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


def burn_captions(
    video_path: str,
    output_path: str,
    words: list[dict],
    style_name: str = "neon",
) -> CaptionResult:
    """Generate ASS subtitles and burn them into the video using FFmpeg."""
    if not os.path.isfile(video_path):
        return CaptionResult(ok=False, error="Video file not found.")

    ff = shutil.which("ffmpeg")
    if not ff:
        return CaptionResult(ok=False, error="FFmpeg not found.")

    ass_content = generate_ass(words, style_name)

    ass_path = output_path + ".tmp_captions.ass"
    try:
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        # Escape path for ASS filter (backslashes and colons)
        escaped = ass_path.replace("\\", "/").replace(":", "\\:")

        cmd = [
            ff, "-y",
            "-i", video_path,
            "-vf", f"ass='{escaped}'",
            "-c:a", "copy",
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
