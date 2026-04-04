"""Groq LLM integration for analyzing transcripts and finding clip-worthy moments."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import requests


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


@dataclass
class ClipSuggestion:
    title: str
    start: float
    end: float
    summary: str
    score: int  # 1-10 virality score


@dataclass
class AIClipResult:
    ok: bool
    clips: list[ClipSuggestion] = field(default_factory=list)
    error: Optional[str] = None


def _format_transcript_with_timestamps(words: list[dict], chunk_seconds: float = 30.0) -> str:
    """Group words into timed chunks for the LLM prompt."""
    if not words:
        return ""

    lines: list[str] = []
    chunk_start = words[0]["start"]
    chunk_words: list[str] = []

    for w in words:
        chunk_words.append(w["word"])
        if w["end"] - chunk_start >= chunk_seconds or w is words[-1]:
            ts_start = _fmt(chunk_start)
            ts_end = _fmt(w["end"])
            lines.append(f"[{ts_start} -> {ts_end}] {' '.join(chunk_words)}")
            chunk_words = []
            if w is not words[-1]:
                chunk_start = words[words.index(w) + 1]["start"] if words.index(w) + 1 < len(words) else w["end"]

    return "\n".join(lines)


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def find_clips(
    transcript_text: str,
    words: list[dict],
    video_duration: float,
    *,
    api_key: str,
    model: str = "llama-3.3-70b-versatile",
    num_clips: int = 5,
    clip_min: int = 30,
    clip_max: int = 90,
) -> AIClipResult:
    if not api_key:
        return AIClipResult(ok=False, error="Groq API key not configured. Go to Settings to add it.")

    timed_transcript = _format_transcript_with_timestamps(words)

    prompt = f"""You are a viral video editor AI. Analyze the following timestamped transcript of a video ({_fmt(video_duration)} long) and find the {num_clips} most engaging, interesting, or viral-worthy segments.

Each clip should be {clip_min}-{clip_max} seconds long. Look for:
- Interesting stories, surprising facts, or emotional moments
- Key insights, tips, or valuable information
- Funny or entertaining segments
- Strong opening hooks or quotable moments
- Complete thoughts (don't cut mid-sentence)

TRANSCRIPT:
{timed_transcript}

Respond ONLY with a JSON array of objects. Each object must have:
- "title": short catchy title for the clip (max 60 chars)
- "start": start time in seconds (number)
- "end": end time in seconds (number)
- "summary": 1-sentence description of why this segment is engaging
- "score": virality score 1-10

Return ONLY the JSON array, no other text. Example:
[{{"title":"The Shocking Truth","start":45.0,"end":120.0,"summary":"Speaker reveals unexpected insight about...","score":8}}]"""

    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a JSON-only response bot. Return only valid JSON arrays."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 2000,
            },
            timeout=60,
        )

        if resp.status_code != 200:
            err = resp.json().get("error", {}).get("message", resp.text[:500])
            return AIClipResult(ok=False, error=f"Groq API error ({resp.status_code}): {err}")

        content = resp.json()["choices"][0]["message"]["content"].strip()

        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if not json_match:
            return AIClipResult(ok=False, error="AI did not return valid JSON.")

        raw_clips = json.loads(json_match.group())

        clips = []
        for c in raw_clips:
            start = float(c.get("start", 0))
            end = float(c.get("end", 0))
            if end <= start or start < 0 or end > video_duration + 5:
                continue
            clips.append(ClipSuggestion(
                title=str(c.get("title", "Untitled"))[:60],
                start=round(start, 1),
                end=round(end, 1),
                summary=str(c.get("summary", ""))[:200],
                score=max(1, min(10, int(c.get("score", 5)))),
            ))

        clips.sort(key=lambda x: x.score, reverse=True)

        if not clips:
            return AIClipResult(ok=False, error="AI could not identify clip-worthy segments.")

        return AIClipResult(ok=True, clips=clips)

    except requests.exceptions.Timeout:
        return AIClipResult(ok=False, error="Groq API timed out. Try again.")
    except json.JSONDecodeError:
        return AIClipResult(ok=False, error="AI returned invalid JSON. Try again.")
    except Exception as e:
        return AIClipResult(ok=False, error=str(e))
