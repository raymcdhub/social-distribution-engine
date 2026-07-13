"""Algorithm 3 (stop posting unavailable listings) then Algorithm 2 (repost
after 4 days), run in that order so a listing removed today is never
reposted today.

Algorithm 3 marks a listing unavailable if its Sanity document id is no
longer present in the live query results — simpler and more reliable than
polling each listing URL for a 404, since Sanity is the source of truth.

Usage: python scripts/daily_maintenance.py [--dry-run]
"""

import json
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import db
import meta
import notify
import sanity_client

REPOST_AFTER = timedelta(days=4)


def run_algorithm_3(conn, dry_run):
    live_ids = {listing["id"] for listing in sanity_client.fetch_listings()}
    removed = 0
    for row in db.get_available(conn):
        if row["id"] not in live_ids:
            print(f"No longer live, marking unavailable: {row['title']} ({row['id']})")
            removed += 1
            if not dry_run:
                db.mark_unavailable(conn, row["id"])
    if not dry_run:
        conn.commit()
    print(f"Algorithm 3: {removed} listing(s) marked unavailable.")


def run_algorithm_2(conn, dry_run):
    now = datetime.now(timezone.utc)
    reposted = 0
    for row in db.get_available(conn):
        last_posted = datetime.fromisoformat(row["last_posted_at"])
        if now - last_posted < REPOST_AFTER:
            continue

        print(f"Reposting: {row['title']} ({row['id']})")
        if dry_run:
            reposted += 1
            continue

        try:
            image_urls = json.loads(row["images"])
            meta.post_to_instagram(image_urls, row["caption"])
            meta.post_to_facebook(image_urls, row["caption"])
            db.touch_last_posted(conn, row["id"])
            conn.commit()
            reposted += 1
        except Exception:
            error = traceback.format_exc()
            print(error, file=sys.stderr)
            notify.send_error_email(
                subject=f"HomeShare repost failed: {row['title']}",
                body=f"Listing: {row['url']}\n\n{error}",
            )
    print(f"Algorithm 2: {reposted} listing(s) reposted.")


def main():
    dry_run = "--dry-run" in sys.argv
    conn = db.connect()
    run_algorithm_3(conn, dry_run)
    run_algorithm_2(conn, dry_run)


if __name__ == "__main__":
    main()
