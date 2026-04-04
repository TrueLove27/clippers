"""SQLite user database for authentication."""

from __future__ import annotations

import os
import sqlite3

from werkzeug.security import check_password_hash, generate_password_hash

_ON_RENDER = bool(os.environ.get("RENDER"))
if _ON_RENDER:
    DB_PATH = "/tmp/clippers_users.db"
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.db")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT    UNIQUE NOT NULL,
                name          TEXT    NOT NULL,
                password_hash TEXT,
                google_id     TEXT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def create_user(
    email: str, name: str, password: str | None = None, google_id: str | None = None
) -> dict | None:
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO users (email, name, password_hash, google_id) VALUES (?, ?, ?, ?)",
                (email, name, generate_password_hash(password) if password else None, google_id),
            )
            return get_user_by_email(email)
    except sqlite3.IntegrityError:
        return None


def get_user_by_email(email: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(uid: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(row) if row else None


def verify_user(email: str, password: str) -> dict | None:
    user = get_user_by_email(email)
    if user and user["password_hash"] and check_password_hash(user["password_hash"], password):
        return user
    return None
