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

Before any of that, listings no longer live on Sanity (unpublished, or
marked "Shortlisting Complete") are marked unavailable, so they're never
picked in step 1-3 above — and ones that have come back live are made
available again, rejoining the rotation.

A repost first checks whether the listing was edited on Sanity (e.g. a
price change) since its caption was written, and regenerates it if so.
Captions never carry a link (Meta caps organic link posts per Page) — the
call to action is "Apply in bio". Instagram and Facebook are posted to
independently, so one failing never stops the other.

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


POSTERS = {"ig": meta.post_to_instagram, "fb": meta.post_to_facebook}


def sync_availability(conn, live_ids, dry_run):
    removed = 0
    restored = 0
    for listing_id in db.get_all_ids(conn):
        row = db.get(conn, listing_id)
        if row["available"] and listing_id not in live_ids:
            print(f"No longer live, marking unavailable: {row['title']} ({listing_id})")
            removed += 1
            if not dry_run:
                db.mark_unavailable(conn, listing_id)
        elif not row["available"] and listing_id in live_ids:
            # Re-published, or reopened after shortlisting. Its old
            # last_posted_at puts it near the front of the rotation.
            print(f"Live again, marking available: {row['title']} ({listing_id})")
            restored += 1
            if not dry_run:
                db.mark_available(conn, listing_id)
    if not dry_run:
        conn.commit()
    if removed:
        print(f"Marked {removed} listing(s) unavailable.")
    if restored:
        print(f"Marked {restored} listing(s) available again.")


def _post_to_platforms(image_urls, listing_caption, platforms, on_posted=lambda name: None):
    """Post to each platform in turn; a failure on one doesn't stop the
    others. Raises after trying them all if any failed."""
    listing_caption = caption_mod.apply_in_bio(listing_caption)
    errors = []
    for name in platforms:
        try:
            POSTERS[name](image_urls, listing_caption)
        except Exception:
            errors.append(f"{name} failed:\n{traceback.format_exc()}")
            continue
        on_posted(name)
    if errors:
        raise RuntimeError("\n".join(errors))


def _post_to_pending_platforms(conn, listing_id, image_urls, listing_caption):
    row = db.get(conn, listing_id)

    def on_posted(name):
        db.mark_posted(conn, listing_id, **{name: True})
        conn.commit()

    pending = [name for name in POSTERS if not row[f"{name}_posted"]]
    _post_to_platforms(image_urls, listing_caption, pending, on_posted)


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


def _is_edited(row, listing):
    return row["title"] != listing["title"] or row["description"] != listing["description"]


def refresh_if_edited(conn, row, listing):
    """Regenerate a stored caption whose listing was edited on Sanity since
    (e.g. a price drop), so a repost never advertises stale details."""
    if not _is_edited(row, listing):
        return row
    print(f"Edited on Sanity since its caption was written, regenerating: {listing['title']}")
    listing_caption = caption_mod.generate_caption(listing)
    transformed_images = images.transform_all(listing["images"])
    db.update_content(conn, listing, listing_caption, transformed_images)
    conn.commit()
    return db.get(conn, row["id"])


def repost(conn, row, listing, dry_run):
    print(f"Reposting (round-robin): {row['title']} ({row['id']})")
    if dry_run:
        if listing and _is_edited(row, listing):
            print(f"Would regenerate caption first, now titled: {listing['title']}")
        print("--- DRY RUN, would repost ---")
        return
    try:
        row = refresh_if_edited(conn, row, listing)
        _post_to_platforms(json.loads(row["images"]), row["caption"], POSTERS)
    finally:
        # Advance the rotation even on failure (permanent or a one-off
        # Meta/Cloudinary/OpenRouter blip) so a single bad listing can't
        # wedge itself at the front of the queue and block every other
        # listing's turn forever, the way Donegal Town and Ardrahan both
        # did. It'll simply come back around for its next turn.
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

    live_by_id = {listing["id"]: listing for listing in live_listings}
    sync_availability(conn, set(live_by_id), dry_run)

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
            repost(conn, next_repost, live_by_id.get(next_repost["id"]), dry_run)
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
