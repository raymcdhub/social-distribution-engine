"""SQLite state, committed back to the repo the same way the email watcher
commits data/seen_opportunities.json — no external database dependency."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_FILE = Path(__file__).parent.parent / "data" / "homeshare.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    images TEXT NOT NULL,
    caption TEXT NOT NULL,
    ig_posted INTEGER NOT NULL DEFAULT 0,
    fb_posted INTEGER NOT NULL DEFAULT 0,
    available INTEGER NOT NULL DEFAULT 1,
    first_posted_at TEXT NOT NULL,
    last_posted_at TEXT NOT NULL
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def connect():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def is_bootstrapped(conn):
    row = conn.execute("SELECT COUNT(*) AS n FROM listings").fetchone()
    return row["n"] > 0


def get(conn, listing_id):
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    return dict(row) if row else None

def get_all_ids(conn):
    return {row["id"] for row in conn.execute("SELECT id FROM listings")}


def get_available(conn):
    rows = conn.execute("SELECT * FROM listings WHERE available = 1").fetchall()
    return [dict(row) for row in rows]


def get_pending_available(conn):
    """Available listings with an incomplete post (e.g. Instagram succeeded,
    Facebook failed on a prior cycle) — always finished before anything new
    is started, in the order they were first inserted."""
    rows = conn.execute(
        """
        SELECT * FROM listings
        WHERE available = 1 AND (ig_posted = 0 OR fb_posted = 0)
        ORDER BY rowid ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_next_repost(conn):
    """The available, fully-posted listing that's least recently posted —
    the next one due in the round-robin rotation."""
    row = conn.execute(
        """
        SELECT * FROM listings
        WHERE available = 1 AND ig_posted = 1 AND fb_posted = 1
        ORDER BY last_posted_at ASC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def upsert_bootstrap(conn, listing):
    """Seed a listing as already-posted, without actually posting it."""
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO listings
            (id, url, title, description, images, caption,
             ig_posted, fb_posted, available, first_posted_at, last_posted_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, 1, 1, ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (
            listing["id"],
            listing["url"],
            listing["title"],
            listing["description"],
            json.dumps(listing["images"]),
            listing.get("caption", ""),
            timestamp,
            timestamp,
        ),
    )


def upsert_new_listing(conn, listing, caption, transformed_images):
    """Insert or update a listing's static content (called before/around posting)."""
    existing = get(conn, listing["id"])
    timestamp = now_iso()
    if existing is None:
        conn.execute(
            """
            INSERT INTO listings
                (id, url, title, description, images, caption,
                 ig_posted, fb_posted, available, first_posted_at, last_posted_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, 1, ?, ?)
            """,
            (
                listing["id"],
                listing["url"],
                listing["title"],
                listing["description"],
                json.dumps(transformed_images),
                caption,
                timestamp,
                timestamp,
            ),
        )


def mark_posted(conn, listing_id, *, ig=None, fb=None):
    updates = []
    params = []
    if ig is not None:
        updates.append("ig_posted = ?")
        params.append(1 if ig else 0)
    if fb is not None:
        updates.append("fb_posted = ?")
        params.append(1 if fb else 0)
    if not updates:
        return
    params.append(listing_id)
    conn.execute(f"UPDATE listings SET {', '.join(updates)} WHERE id = ?", params)


def touch_last_posted(conn, listing_id):
    conn.execute(
        "UPDATE listings SET last_posted_at = ? WHERE id = ?",
        (now_iso(), listing_id),
    )


def mark_unavailable(conn, listing_id):
    conn.execute("UPDATE listings SET available = 0 WHERE id = ?", (listing_id,))
