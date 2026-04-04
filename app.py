"""
Clippers — AI Reel Generator.
Paste a YouTube link, get short reels with animated subtitles.
Local:  python app.py
Render: gunicorn app:app
"""

from __future__ import annotations

import os
import threading
import uuid

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
from downloader import download_url
from clipper import clip_video
from captioner import burn_captions

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_ON_RENDER = bool(os.environ.get("RENDER"))
GOOGLE_CLIENT_ID: str | None = os.environ.get("GOOGLE_CLIENT_ID")

if _ON_RENDER:
    WORK_DIR = "/tmp/clippers"
else:
    WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_output")

DOWNLOAD_DIR = os.path.join(WORK_DIR, "downloads")
REELS_DIR = os.path.join(WORK_DIR, "reels")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clippers-dev-key-change-in-prod")

login_manager = LoginManager(app)
login_manager.login_view = "landing"


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error="Not authenticated."), 401
    return redirect(url_for("landing"))

db.init_db()
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(REELS_DIR, exist_ok=True)


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
# In-memory task store
# ---------------------------------------------------------------------------
_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def _set_task(tid: str, data: dict):
    with _lock:
        _tasks[tid] = data


def _get_task(tid: str) -> dict | None:
    with _lock:
        return _tasks.get(tid)


def _update_msg(tid: str, msg: str):
    task = _get_task(tid)
    if task:
        task["message"] = msg
        _set_task(tid, task)


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
    return render_template("dashboard.html", user_name=current_user.name)


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
        return jsonify(ok=False, error="Name, email and password (min 6 chars) required."), 400
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
        return jsonify(ok=False, error="Google sign-in is not configured."), 501
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
               "clip_duration_max", "caption_style", "whisper_model",
               "auto_captions", "output_format"}
    updates = {k: v for k, v in data.items() if k in allowed}
    c = cfg.save(updates)
    return jsonify(ok=True, has_api_key=bool(c.get("groq_api_key")))


# ---------------------------------------------------------------------------
# Serve generated reels
# ---------------------------------------------------------------------------

@app.route("/api/reels/serve")
@login_required
def serve_reel():
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        return "Not found", 404
    return send_from_directory(
        os.path.dirname(path), os.path.basename(path), conditional=True
    )


# ---------------------------------------------------------------------------
# AI Reel generation pipeline
# ---------------------------------------------------------------------------

@app.route("/api/generate", methods=["POST"])
@login_required
def start_generate():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify(ok=False, error="No URL provided."), 400

    settings = cfg.load()
    api_key = settings.get("groq_api_key", "")
    if not api_key:
        return jsonify(ok=False, error="Groq API key not configured. Open Settings to add it."), 400

    tid = uuid.uuid4().hex[:12]
    _set_task(tid, {
        "status": "running",
        "step": "downloading",
        "step_num": 1,
        "total_steps": 5,
        "progress": 0,
        "message": "Downloading video...",
        "error": None,
        "reels": [],
    })

    def pipeline():
        task = _get_task(tid)
        if not task:
            return

        # ---- Step 1: Download ------------------------------------------------
        def dl_progress(_kind, st):
            p = st.get("percent")
            if p is not None:
                task["progress"] = int(p * 0.20)
                _set_task(tid, task)

        dl = download_url(url, DOWNLOAD_DIR, progress=dl_progress)
        if not dl.ok:
            task.update(status="error", error=dl.error or "Download failed.")
            _set_task(tid, task)
            return

        video_path = dl.filepath or ""
        if video_path and not video_path.lower().endswith(".mp4"):
            base = os.path.splitext(video_path)[0]
            for ext in [".mp4", ".webm", ".mkv"]:
                candidate = base + ext
                if os.path.isfile(candidate):
                    video_path = candidate
                    break

        task["progress"] = 20

        # ---- Step 2: Transcribe ----------------------------------------------
        task.update(step="transcribing", step_num=2, message="Transcribing audio with AI...")
        _set_task(tid, task)

        from transcriber import transcribe
        tr = transcribe(
            video_path,
            model_size=settings.get("whisper_model", "whisper-large-v3"),
            on_progress=lambda msg: _update_msg(tid, msg),
            api_key=api_key,
        )
        if not tr.ok:
            task.update(status="error", error=tr.error or "Transcription failed.")
            _set_task(tid, task)
            return

        words = [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                 for w in tr.words]
        task["progress"] = 40

        # ---- Step 3: AI finds best moments -----------------------------------
        task.update(step="analyzing", step_num=3, message="AI is finding the best moments...")
        _set_task(tid, task)

        from ai_engine import find_clips
        ai = find_clips(
            tr.text, words, tr.duration,
            api_key=api_key,
            model=settings.get("model", "llama-3.3-70b-versatile"),
            num_clips=int(settings.get("num_clips", 8)),
            clip_min=int(settings.get("clip_duration_min", 15)),
            clip_max=int(settings.get("clip_duration_max", 25)),
        )
        if not ai.ok:
            task.update(status="error", error=ai.error or "AI analysis failed.")
            _set_task(tid, task)
            return

        task["progress"] = 55

        # ---- Step 4: Extract clips -------------------------------------------
        task.update(step="extracting", step_num=4, message="Cutting clips...")
        _set_task(tid, task)

        reel_dir = os.path.join(REELS_DIR, tid)
        os.makedirs(reel_dir, exist_ok=True)

        raw_clips = []
        for i, c in enumerate(ai.clips):
            safe_title = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in c.title)[:40].strip()
            raw_name = f"{i+1:02d}_{safe_title}_raw.mp4"
            raw_path = os.path.join(reel_dir, raw_name)
            cr = clip_video(video_path, raw_path, str(c.start), end=str(c.end))

            clip_words = [w for w in words if w["start"] >= c.start - 0.5 and w["end"] <= c.end + 0.5]
            offset_words = [
                {"word": w["word"],
                 "start": round(w["start"] - c.start, 3),
                 "end": round(w["end"] - c.start, 3),
                 "probability": w["probability"]}
                for w in clip_words
            ]

            raw_clips.append({
                "title": c.title,
                "summary": c.summary,
                "score": c.score,
                "start": c.start,
                "end": c.end,
                "duration": round(c.end - c.start, 1),
                "raw_path": raw_path if cr.ok else None,
                "words": offset_words,
                "ok": cr.ok,
                "error": cr.error if not cr.ok else None,
            })

            pct = 55 + int((i + 1) / len(ai.clips) * 20)
            task["progress"] = min(pct, 75)
            _set_task(tid, task)

        task["progress"] = 75

        # ---- Step 5: Burn subtitles + vertical format ------------------------
        task.update(step="captioning", step_num=5,
                    message="Adding animated subtitles & converting to vertical...")
        _set_task(tid, task)

        style = settings.get("caption_style", "neon")
        vertical = settings.get("output_format", "vertical") == "vertical"
        reel_results = []

        for i, clip_data in enumerate(raw_clips):
            if not clip_data["ok"] or not clip_data["raw_path"]:
                reel_results.append({
                    "title": clip_data["title"],
                    "summary": clip_data["summary"],
                    "score": clip_data["score"],
                    "duration": clip_data["duration"],
                    "path": None,
                    "ok": False,
                    "error": clip_data.get("error", "Clip extraction failed."),
                })
                continue

            safe_title = "".join(
                ch if ch.isalnum() or ch in " _-" else "_"
                for ch in clip_data["title"]
            )[:40].strip()
            reel_name = f"{i+1:02d}_{safe_title}.mp4"
            reel_path = os.path.join(reel_dir, reel_name)

            if clip_data["words"]:
                cap = burn_captions(
                    clip_data["raw_path"], reel_path,
                    clip_data["words"], style_name=style, vertical=vertical,
                )
            else:
                from captioner import convert_to_vertical
                if vertical:
                    result = convert_to_vertical(clip_data["raw_path"], reel_path)
                    cap = type("R", (), {"ok": bool(result), "output_path": reel_path, "error": None})()
                else:
                    import shutil as sh
                    sh.copy2(clip_data["raw_path"], reel_path)
                    cap = type("R", (), {"ok": True, "output_path": reel_path, "error": None})()

            reel_results.append({
                "title": clip_data["title"],
                "summary": clip_data["summary"],
                "score": clip_data["score"],
                "duration": clip_data["duration"],
                "path": reel_path if cap.ok else None,
                "ok": cap.ok,
                "error": cap.error if not cap.ok else None,
            })

            # Clean up raw clip
            try:
                if clip_data["raw_path"] and os.path.isfile(clip_data["raw_path"]):
                    os.remove(clip_data["raw_path"])
            except OSError:
                pass

            pct = 75 + int((i + 1) / len(raw_clips) * 25)
            task["progress"] = min(pct, 100)
            task["message"] = f"Processing reel {i+1}/{len(raw_clips)}..."
            _set_task(tid, task)

        ok_count = len([r for r in reel_results if r["ok"]])
        task.update(
            reels=reel_results,
            progress=100,
            step="done",
            status="done",
            message=f"Generated {ok_count} reel{'s' if ok_count != 1 else ''}!",
        )
        _set_task(tid, task)

    threading.Thread(target=pipeline, daemon=True).start()
    return jsonify(ok=True, task_id=tid)


@app.route("/api/generate/progress/<tid>")
@login_required
def generation_progress(tid: str):
    task = _get_task(tid)
    if not task:
        return jsonify(ok=False, error="Unknown task."), 404
    return jsonify(ok=True, **task)


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f" * Work dir -> {WORK_DIR}")
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
