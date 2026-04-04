"""Speech-to-text transcription with word-level timestamps.

Supports two modes:
  - 'cloud'  : Groq Whisper API (works on Render, no GPU needed)
  - 'local'  : faster-whisper (needs GPU or beefy CPU, runs offline)
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

import requests as http_requests


@dataclass
class WordInfo:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class TranscriptResult:
    ok: bool
    text: str = ""
    words: list[WordInfo] = field(default_factory=list)
    language: str = ""
    duration: float = 0.0
    error: Optional[str] = None


GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MAX_CHUNK_MB = 24  # Groq limit is 25 MB; stay under


# ---------------------------------------------------------------------------
#  Audio extraction helpers
# ---------------------------------------------------------------------------

def _ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def _ffprobe() -> Optional[str]:
    return shutil.which("ffprobe")


def _extract_audio_mp3(video_path: str) -> Optional[str]:
    """Extract audio as MP3 (small size for cloud upload)."""
    ff = _ffmpeg()
    if not ff:
        return None
    audio_path = video_path + ".tmp_audio.mp3"
    cmd = [ff, "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame",
           "-ar", "16000", "-ac", "1", "-b:a", "64k", audio_path]
    try:
        subprocess.run(cmd, capture_output=True, text=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if os.path.isfile(audio_path):
            return audio_path
    except Exception:
        pass
    return None


def _extract_audio_wav(video_path: str) -> Optional[str]:
    """Extract audio as WAV (for local faster-whisper)."""
    ff = _ffmpeg()
    if not ff:
        return None
    audio_path = video_path + ".tmp_audio.wav"
    cmd = [ff, "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le",
           "-ar", "16000", "-ac", "1", audio_path]
    try:
        subprocess.run(cmd, capture_output=True, text=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if os.path.isfile(audio_path):
            return audio_path
    except Exception:
        pass
    return None


def _get_duration(path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    fp = _ffprobe()
    if not fp:
        return 0.0
    try:
        r = subprocess.run(
            [fp, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _split_audio(audio_path: str, max_mb: int = MAX_CHUNK_MB) -> list[str]:
    """Split audio into chunks if larger than max_mb."""
    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if size_mb <= max_mb:
        return [audio_path]

    duration = _get_duration(audio_path)
    if duration <= 0:
        return [audio_path]

    num_chunks = math.ceil(size_mb / max_mb)
    chunk_dur = duration / num_chunks
    ff = _ffmpeg()
    chunks: list[str] = []

    for i in range(num_chunks):
        start = i * chunk_dur
        chunk_path = f"{audio_path}.chunk{i}.mp3"
        cmd = [ff, "-y", "-i", audio_path, "-ss", str(start), "-t", str(chunk_dur),
               "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-b:a", "64k", chunk_path]
        subprocess.run(cmd, capture_output=True, text=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if os.path.isfile(chunk_path):
            chunks.append(chunk_path)

    return chunks if chunks else [audio_path]


# ---------------------------------------------------------------------------
#  Cloud mode: Groq Whisper API
# ---------------------------------------------------------------------------

def _transcribe_cloud(
    video_path: str,
    api_key: str,
    model: str = "whisper-large-v3",
    on_progress=None,
) -> TranscriptResult:
    if on_progress:
        on_progress("Extracting audio...")

    audio_path = _extract_audio_mp3(video_path)
    if not audio_path:
        return TranscriptResult(ok=False, error="Failed to extract audio. Is FFmpeg installed?")

    cleanup: list[str] = [audio_path]

    try:
        if on_progress:
            on_progress("Preparing audio for cloud transcription...")

        chunks = _split_audio(audio_path)
        cleanup.extend(c for c in chunks if c != audio_path)

        all_words: list[WordInfo] = []
        full_text_parts: list[str] = []
        time_offset = 0.0

        for i, chunk in enumerate(chunks):
            if on_progress and len(chunks) > 1:
                on_progress(f"Transcribing chunk {i+1}/{len(chunks)}...")
            elif on_progress:
                on_progress("Sending to Groq Whisper API...")

            with open(chunk, "rb") as f:
                resp = http_requests.post(
                    GROQ_AUDIO_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (os.path.basename(chunk), f, "audio/mpeg")},
                    data={
                        "model": model,
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "word",
                    },
                    timeout=120,
                )

            if resp.status_code != 200:
                err = resp.json().get("error", {}).get("message", resp.text[:500])
                return TranscriptResult(ok=False, error=f"Groq Whisper error: {err}")

            data = resp.json()
            full_text_parts.append(data.get("text", ""))

            for w in data.get("words", []):
                all_words.append(WordInfo(
                    word=w.get("word", "").strip(),
                    start=round(w.get("start", 0) + time_offset, 3),
                    end=round(w.get("end", 0) + time_offset, 3),
                    probability=0.95,
                ))

            if len(chunks) > 1:
                time_offset += _get_duration(chunk)

        total_duration = _get_duration(audio_path)

        return TranscriptResult(
            ok=True,
            text=" ".join(full_text_parts),
            words=all_words,
            language=data.get("language", "en") if 'data' in dir() else "en",
            duration=total_duration,
        )

    except http_requests.exceptions.Timeout:
        return TranscriptResult(ok=False, error="Groq Whisper API timed out.")
    except Exception as e:
        return TranscriptResult(ok=False, error=str(e))
    finally:
        for p in cleanup:
            if p and os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
#  Local mode: faster-whisper (GPU/CPU)
# ---------------------------------------------------------------------------

_model = None
_model_size = None


def _get_model(model_size: str = "large-v3"):
    global _model, _model_size
    if _model is not None and _model_size == model_size:
        return _model

    from faster_whisper import WhisperModel

    for device, compute in [("cuda", "float16"), ("cpu", "int8")]:
        try:
            _model = WhisperModel(model_size, device=device, compute_type=compute)
            _model_size = model_size
            print(f" * Whisper loaded on {device} ({compute})")
            return _model
        except Exception:
            if device == "cpu":
                raise
            continue

    raise RuntimeError("Could not load Whisper model on any device.")


def _transcribe_local(
    video_path: str,
    model_size: str = "large-v3",
    on_progress=None,
) -> TranscriptResult:
    if on_progress:
        on_progress("Extracting audio...")

    audio_path = _extract_audio_wav(video_path)
    if not audio_path:
        return TranscriptResult(ok=False, error="Failed to extract audio. Is FFmpeg installed?")

    try:
        if on_progress:
            on_progress("Loading Whisper model...")

        model = _get_model(model_size)

        if on_progress:
            on_progress("Transcribing...")

        segments, info = model.transcribe(audio_path, beam_size=5, word_timestamps=True, vad_filter=True)

        all_words: list[WordInfo] = []
        full_text_parts: list[str] = []

        for segment in segments:
            full_text_parts.append(segment.text.strip())
            if segment.words:
                for w in segment.words:
                    all_words.append(WordInfo(
                        word=w.word.strip(),
                        start=round(w.start, 3),
                        end=round(w.end, 3),
                        probability=round(w.probability, 3),
                    ))

        return TranscriptResult(
            ok=True,
            text=" ".join(full_text_parts),
            words=all_words,
            language=info.language,
            duration=info.duration,
        )
    except Exception as e:
        return TranscriptResult(ok=False, error=str(e))
    finally:
        if audio_path and os.path.isfile(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
#  Public API — auto-selects cloud vs local
# ---------------------------------------------------------------------------

def transcribe(
    video_path: str,
    model_size: str = "large-v3",
    on_progress=None,
    api_key: str = "",
    mode: str = "auto",
) -> TranscriptResult:
    """Transcribe a video file.

    mode='cloud'  -> Groq Whisper API (needs api_key)
    mode='local'  -> faster-whisper on GPU/CPU
    mode='auto'   -> cloud if api_key is set, else local
    """
    if not os.path.isfile(video_path):
        return TranscriptResult(ok=False, error="Video file not found.")

    use_cloud = (mode == "cloud") or (mode == "auto" and api_key)

    if use_cloud:
        if not api_key:
            return TranscriptResult(ok=False, error="Groq API key required for cloud transcription.")
        return _transcribe_cloud(video_path, api_key, on_progress=on_progress)

    return _transcribe_local(video_path, model_size, on_progress=on_progress)
