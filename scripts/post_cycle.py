"""Runs twice a day. Posts exactly one opportunity per run, so every active
listing gets an equal, fair turn: no listing is posted a second time until
every other active listing has had its first (or next) turn.

Order of priority each run:
  1. Finish any post left incomplete by a prior run (e.g. Instagram
     succeeded, Facebook errored) — using the already-generated caption and
     images, no regeneration.
  2. Post the oldest brand-new listing not yet known to the database at all
     — new listings jump to the front of the queue rather than waiting out
     a full rotation.
  3. Otherwise, repost whichever available listing was posted longest ago
     (round-robin) — this is what guarantees fairness over time.

Before any of that, listings no longer live on Sanity are marked
unavailable, so a delisted listing is never picked in step 1-3 above.

First run bootstraps: seeds the database with every listing currently live,
marked as already-posted, without sending anything — otherwise go-live
would post every existing listing at once.

Usage: python scripts/post_cycle.py [--dry-run]
"""

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import caption as caption_mod
import db
import images
import meta
import notify
import sanity_client


def mark_delisted(conn, live_ids, dry_run):
    removed = 0
    for row in db.get_available(conn):
        if row["id"] not in live_ids:
            print(f"No longer live, marking unavailable: {row['title']} ({row['id']})")
            removed += 1
            if not dry_run:
                db.mark_unavailable(conn, row["id"])
    if not dry_run:
        conn.commit()
    if removed:
        print(f"Marked {removed} listing(s) unavailable.")


def _post_to_pending_platforms(conn, listing_id, image_urls, listing_caption):
    row = db.get(conn, listing_id)
    if not row["ig_posted"]:
        meta.post_to_instagram(image_urls, listing_caption)
        db.mark_posted(conn, listing_id, ig=True)
        conn.commit()
    if not row["fb_posted"]:
        meta.post_to_facebook(image_urls, listing_caption)
        db.mark_posted(conn, listing_id, fb=True)
        conn.commit()


def finish_pending(conn, row, dry_run):
    print(f"Finishing incomplete post: {row['title']} ({row['id']})")
    if dry_run:
        print("--- DRY RUN, would retry pending platform(s) ---")
        return
    image_urls = json.loads(row["images"])
    _post_to_pending_platforms(conn, row["id"], image_urls, row["caption"])
    print(f"Completed: {row['title']}")


def post_new_listing(conn, listing, dry_run):
    print(f"New listing: {listing['title']} ({listing['id']})")
    listing_caption = caption_mod.generate_caption(listing)
    transformed_images = images.transform_all(listing["images"])

    if dry_run:
        print("--- DRY RUN, not posting or saving ---")
        print("Caption:\n", listing_caption)
        print("Images:", transformed_images)
        return

    db.upsert_new_listing(conn, listing, listing_caption, transformed_images)
    conn.commit()
    _post_to_pending_platforms(conn, listing["id"], transformed_images, listing_caption)
    print(f"Posted: {listing['title']}")


def repost(conn, row, dry_run):
    print(f"Reposting (round-robin): {row['title']} ({row['id']})")
    if dry_run:
        print("--- DRY RUN, would repost ---")
        return
    image_urls = json.loads(row["images"])
    meta.post_to_instagram(image_urls, row["caption"])
    meta.post_to_facebook(image_urls, row["caption"])
    db.touch_last_posted(conn, row["id"])
    conn.commit()
    print(f"Reposted: {row['title']}")


def main():
    dry_run = "--dry-run" in sys.argv

    live_listings = sanity_client.fetch_listings()
    if not live_listings:
        print("No listings returned from Sanity — skipping.", file=sys.stderr)
        return

    conn = db.connect()

    if not db.is_bootstrapped(conn):
        for listing in live_listings:
            db.upsert_bootstrap(conn, listing)
        conn.commit()
        print(f"Bootstrapped database with {len(live_listings)} existing listings (no posts sent).")
        return

    live_ids = {listing["id"] for listing in live_listings}
    mark_delisted(conn, live_ids, dry_run)

    known_ids = db.get_all_ids(conn)

    try:
        pending = db.get_pending_available(conn)
        if pending:
            finish_pending(conn, pending[0], dry_run)
            return

        new_listings = sorted(
            (listing for listing in live_listings if listing["id"] not in known_ids),
            key=lambda listing: listing["date_listed"],
        )
        if new_listings:
            post_new_listing(conn, new_listings[0], dry_run)
            return

        next_repost = db.get_next_repost(conn)
        if next_repost:
            repost(conn, next_repost, dry_run)
            return

        print("Nothing to post this cycle.")
    except Exception:
        error = traceback.format_exc()
        print(error, file=sys.stderr)
        notify.send_error_email(
            subject="HomeShare social post cycle failed",
            body=error,
        )


if __name__ == "__main__":
    main()
