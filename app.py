"""
Clippers — Flask web application.
Local:  python app.py
Render: gunicorn app:app
"""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)

import database as db
import config_manager as cfg
from clipper import clip_video
from downloader import download_playlist, download_url

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_ON_RENDER = bool(os.environ.get("RENDER"))
GOOGLE_CLIENT_ID: str | None = os.environ.get("GOOGLE_CLIENT_ID")

if _ON_RENDER:
    DOWNLOAD_DIR = "/tmp/clippers/downloads"
    CLIP_DIR = "/tmp/clippers/clips"
else:
    DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Videos", "VideoGrabber")
    CLIP_DIR = os.path.join(DOWNLOAD_DIR, "Clips")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())

login_manager = LoginManager(app)
login_manager.login_view = "landing"

db.init_db()
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(CLIP_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# User model wrapper for Flask-Login
# ---------------------------------------------------------------------------

class User(UserMixin):
    def __init__(self, data: dict):
        self._data = data

    def get_id(self):
        return str(self._data["id"])

    @property
    def name(self):
        return self._data["name"]

    @property
    def email(self):
        return self._data["email"]


@login_manager.user_loader
def load_user(uid: str):
    data = db.get_user_by_id(int(uid))
    return User(data) if data else None


# ---------------------------------------------------------------------------
# In-memory download progress store
# ---------------------------------------------------------------------------
_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def _set_task(tid: str, data: dict):
    with _lock:
        _tasks[tid] = data


def _get_task(tid: str) -> dict | None:
    with _lock:
        return _tasks.get(tid)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("landing.html", google_client_id=GOOGLE_CLIENT_ID)


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        user_name=current_user.name,
        download_dir=DOWNLOAD_DIR,
        clip_dir=CLIP_DIR,
    )


# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------

@app.route("/api/auth/guest", methods=["POST"])
def guest_login():
    email = "guest@clippers.local"
    user = db.get_user_by_email(email)
    if not user:
        user = db.create_user(email, "Guest", password="guest-dev-mode")
    if not user:
        return jsonify(ok=False, error="Could not create guest account."), 500
    login_user(User(user), remember=True)
    return jsonify(ok=True)


@app.route("/api/auth/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    password = data.get("password") or ""
    if not email or not name or len(password) < 6:
        return jsonify(ok=False, error="Name, email and password (≥6 chars) required."), 400
    user = db.create_user(email, name, password=password)
    if not user:
        return jsonify(ok=False, error="An account with this email already exists."), 409
    login_user(User(user), remember=True)
    return jsonify(ok=True)


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    user = db.verify_user(email, password)
    if not user:
        return jsonify(ok=False, error="Invalid email or password."), 401
    login_user(User(user), remember=True)
    return jsonify(ok=True)


@app.route("/api/auth/google", methods=["POST"])
def google_auth():
    if not GOOGLE_CLIENT_ID:
        return jsonify(ok=False, error="Google sign-in is not configured on the server."), 501
    token = (request.get_json(silent=True) or {}).get("credential")
    if not token:
        return jsonify(ok=False, error="Missing token."), 400
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        info = id_token.verify_oauth2_token(token, g_requests.Request(), GOOGLE_CLIENT_ID)
        email = info["email"]
        name = info.get("name", email.split("@")[0])
        gid = info["sub"]
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 401

    user = db.get_user_by_email(email)
    if not user:
        user = db.create_user(email, name, google_id=gid)
    if not user:
        return jsonify(ok=False, error="Could not create account."), 500
    login_user(User(user), remember=True)
    return jsonify(ok=True)


@app.route("/api/auth/logout")
def logout():
    logout_user()
    return redirect(url_for("landing"))


# ---------------------------------------------------------------------------
# Download API
# ---------------------------------------------------------------------------

@app.route("/api/download", methods=["POST"])
@login_required
def start_download():
    data = request.get_json(silent=True) or {}
    urls: list[str] = data.get("urls", [])
    playlist = bool(data.get("playlist"))
    out_dir = data.get("directory") or DOWNLOAD_DIR
    os.makedirs(out_dir, exist_ok=True)

    if not urls:
        return jsonify(ok=False, error="No URLs provided."), 400

    tid = uuid.uuid4().hex[:12]
    items = [{"url": u, "status": "pending", "progress": 0, "error": None} for u in urls]
    _set_task(tid, {"status": "running", "items": items, "playlist": playlist})

    def work():
        task = _get_task(tid)
        if not task:
            return

        for idx, item in enumerate(task["items"]):
            item["status"] = "downloading"
            _set_task(tid, task)

            is_playlist = playlist and idx == 0

            def prog(_kind, st, _item=item):
                p = st.get("percent")
                if p is not None:
                    _item["progress"] = p
                elif st.get("status") == "finished":
                    _item["progress"] = 100
                _set_task(tid, task)

            if is_playlist:
                r = download_playlist(item["url"], out_dir, progress=prog)
            else:
                r = download_url(item["url"], out_dir, progress=prog)

            item["progress"] = 100
            if r.ok:
                item["status"] = "done"
                item["filepath"] = r.filepath
            else:
                item["status"] = "error"
                item["error"] = r.error
            _set_task(tid, task)

        task["status"] = "done"
        _set_task(tid, task)

    threading.Thread(target=work, daemon=True).start()
    return jsonify(ok=True, task_id=tid)


@app.route("/api/download/progress/<tid>")
@login_required
def download_progress(tid: str):
    task = _get_task(tid)
    if not task:
        return jsonify(ok=False, error="Unknown task."), 404
    return jsonify(ok=True, **task)


# ---------------------------------------------------------------------------
# Clip API
# ---------------------------------------------------------------------------

@app.route("/api/clip", methods=["POST"])
@login_required
def create_clip():
    data = request.get_json(silent=True) or {}
    src = data.get("input", "").strip()
    start = data.get("start", "0").strip()
    end = data.get("end", "").strip() or None
    duration = data.get("duration", "").strip() or None
    out_name = data.get("filename", "clip.mp4").strip()
    out_dir = data.get("directory") or CLIP_DIR
    os.makedirs(out_dir, exist_ok=True)

    if not src or not os.path.isfile(src):
        return jsonify(ok=False, error="Input file not found."), 400
    if not end and not duration:
        return jsonify(ok=False, error="Provide end time or duration."), 400

    if not out_name.lower().endswith((".mp4", ".mkv", ".webm", ".mov")):
        out_name += ".mp4"
    out_path = os.path.join(out_dir, out_name)

    res = clip_video(src, out_path, start, end=end, duration=duration)
    if res.ok:
        return jsonify(ok=True, path=res.output_path)
    return jsonify(ok=False, error=res.error), 500


# ---------------------------------------------------------------------------
# File listing API
# ---------------------------------------------------------------------------

@app.route("/api/files")
@login_required
def list_files():
    out: list[dict] = []
    for directory, label in [(DOWNLOAD_DIR, "download"), (CLIP_DIR, "clip")]:
        if not os.path.isdir(directory):
            continue
        for entry in sorted(Path(directory).iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if entry.is_file() and entry.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".avi"}:
                out.append({
                    "name": entry.name,
                    "path": str(entry),
                    "size_mb": round(entry.stat().st_size / 1_048_576, 1),
                    "type": label,
                })
    return jsonify(ok=True, files=out)


@app.route("/api/files/serve")
@login_required
def serve_file():
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        return "Not found", 404
    return send_from_directory(
        os.path.dirname(path), os.path.basename(path), conditional=True
    )


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    c = cfg.load()
    safe = {k: v for k, v in c.items() if k != "groq_api_key"}
    safe["has_api_key"] = bool(c.get("groq_api_key"))
    return jsonify(ok=True, settings=safe)


@app.route("/api/settings", methods=["POST"])
@login_required
def save_settings():
    data = request.get_json(silent=True) or {}
    allowed = {"groq_api_key", "model", "num_clips", "clip_duration_min",
               "clip_duration_max", "caption_style", "whisper_model"}
    updates = {k: v for k, v in data.items() if k in allowed}
    c = cfg.save(updates)
    return jsonify(ok=True, has_api_key=bool(c.get("groq_api_key")))


# ---------------------------------------------------------------------------
# AI Clip pipeline API
# ---------------------------------------------------------------------------

@app.route("/api/ai/clip", methods=["POST"])
@login_required
def start_ai_clip():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify(ok=False, error="No URL provided."), 400

    settings = cfg.load()
    if not settings.get("groq_api_key"):
        return jsonify(ok=False, error="Groq API key not configured. Go to Settings."), 400

    tid = uuid.uuid4().hex[:12]
    _set_task(tid, {
        "type": "ai_clip",
        "status": "running",
        "step": "downloading",
        "step_num": 1,
        "total_steps": 4,
        "progress": 0,
        "message": "Downloading video...",
        "error": None,
        "clips": [],
        "transcript": "",
        "words": [],
        "video_path": "",
        "video_duration": 0,
    })

    def pipeline():
        task = _get_task(tid)
        if not task:
            return

        # Step 1: Download
        def dl_progress(_kind, st):
            p = st.get("percent")
            if p is not None:
                task["progress"] = int(p * 0.25)
                _set_task(tid, task)

        dl_result = download_url(url, DOWNLOAD_DIR, progress=dl_progress)
        if not dl_result.ok:
            task["status"] = "error"
            task["error"] = dl_result.error or "Download failed."
            _set_task(tid, task)
            return

        video_path = dl_result.filepath or ""
        if video_path and not video_path.lower().endswith(".mp4"):
            base = os.path.splitext(video_path)[0]
            for ext in [".mp4", ".webm", ".mkv"]:
                candidate = base + ext
                if os.path.isfile(candidate):
                    video_path = candidate
                    break

        task["video_path"] = video_path
        task["progress"] = 25

        # Step 2: Transcribe
        task["step"] = "transcribing"
        task["step_num"] = 2
        task["message"] = "Transcribing audio with AI..."
        _set_task(tid, task)

        from transcriber import transcribe
        tr = transcribe(
            video_path,
            model_size=settings.get("whisper_model", "large-v3"),
            on_progress=lambda msg: _update_message(tid, msg),
            api_key=settings.get("groq_api_key", ""),
        )
        if not tr.ok:
            task["status"] = "error"
            task["error"] = tr.error or "Transcription failed."
            _set_task(tid, task)
            return

        task["transcript"] = tr.text
        task["words"] = [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability} for w in tr.words]
        task["video_duration"] = tr.duration
        task["progress"] = 50

        # Step 3: AI Analysis
        task["step"] = "analyzing"
        task["step_num"] = 3
        task["message"] = "AI is finding the best moments..."
        _set_task(tid, task)

        from ai_engine import find_clips
        ai_result = find_clips(
            tr.text,
            task["words"],
            tr.duration,
            api_key=settings["groq_api_key"],
            model=settings.get("model", "llama-3.3-70b-versatile"),
            num_clips=int(settings.get("num_clips", 5)),
            clip_min=int(settings.get("clip_duration_min", 30)),
            clip_max=int(settings.get("clip_duration_max", 90)),
        )
        if not ai_result.ok:
            task["status"] = "error"
            task["error"] = ai_result.error or "AI analysis failed."
            _set_task(tid, task)
            return

        task["progress"] = 75

        # Step 4: Extract clips
        task["step"] = "extracting"
        task["step_num"] = 4
        task["message"] = "Extracting clips..."
        _set_task(tid, task)

        ai_clips_dir = os.path.join(CLIP_DIR, "ai_" + tid)
        os.makedirs(ai_clips_dir, exist_ok=True)

        clip_results = []
        for i, c in enumerate(ai_result.clips):
            safe_title = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in c.title)[:40].strip()
            out_name = f"{i+1:02d}_{safe_title}.mp4"
            out_path = os.path.join(ai_clips_dir, out_name)

            from clipper import clip_video as cv
            cr = cv(video_path, out_path, str(c.start), end=str(c.end))

            # Collect words that fall within this clip's time range
            clip_words = [w for w in task["words"]
                          if w["start"] >= c.start - 0.5 and w["end"] <= c.end + 0.5]
            # Offset word times to be relative to clip start
            offset_words = []
            for w in clip_words:
                offset_words.append({
                    "word": w["word"],
                    "start": round(w["start"] - c.start, 3),
                    "end": round(w["end"] - c.start, 3),
                    "probability": w["probability"],
                })

            clip_results.append({
                "title": c.title,
                "summary": c.summary,
                "score": c.score,
                "start": c.start,
                "end": c.end,
                "duration": round(c.end - c.start, 1),
                "path": out_path if cr.ok else None,
                "ok": cr.ok,
                "error": cr.error if not cr.ok else None,
                "words": offset_words,
            })

            pct = 75 + int((i + 1) / len(ai_result.clips) * 25)
            task["progress"] = min(pct, 100)
            _set_task(tid, task)

        task["clips"] = clip_results
        task["progress"] = 100
        task["step"] = "done"
        task["status"] = "done"
        task["message"] = f"Generated {len([c for c in clip_results if c['ok']])} clips!"
        _set_task(tid, task)

    threading.Thread(target=pipeline, daemon=True).start()
    return jsonify(ok=True, task_id=tid)


def _update_message(tid: str, msg: str):
    task = _get_task(tid)
    if task:
        task["message"] = msg
        _set_task(tid, task)


@app.route("/api/ai/clip/progress/<tid>")
@login_required
def ai_clip_progress(tid: str):
    task = _get_task(tid)
    if not task or task.get("type") != "ai_clip":
        return jsonify(ok=False, error="Unknown task."), 404
    safe = {k: v for k, v in task.items() if k != "words"}
    return jsonify(ok=True, **safe)


@app.route("/api/ai/caption", methods=["POST"])
@login_required
def add_captions():
    data = request.get_json(silent=True) or {}
    clip_path = data.get("clip_path", "").strip()
    words = data.get("words", [])
    style = data.get("style", cfg.get("caption_style", "neon"))

    if not clip_path or not os.path.isfile(clip_path):
        return jsonify(ok=False, error="Clip file not found."), 400
    if not words:
        return jsonify(ok=False, error="No word data provided."), 400

    base, ext = os.path.splitext(clip_path)
    out_path = base + "_captioned" + ext

    from captioner import burn_captions
    result = burn_captions(clip_path, out_path, words, style_name=style)

    if result.ok:
        return jsonify(ok=True, path=result.output_path)
    return jsonify(ok=False, error=result.error), 500


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f" * Downloads -> {DOWNLOAD_DIR}")
    print(f" * Clips     -> {CLIP_DIR}")
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
