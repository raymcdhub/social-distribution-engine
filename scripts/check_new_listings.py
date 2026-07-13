"""Algorithm 1 — post on new listing.

Bootstraps on first run (seeds every currently-live listing as already-posted
without actually posting — otherwise go-live would blast every existing
listing to Instagram/Facebook at once). After that, any listing not yet in
the database is posted to Instagram and Facebook. Listings that are already
in the database but only partially posted (e.g. Instagram succeeded, Facebook
failed on a previous run) are retried using their already-generated caption
and images, without re-calling Groq/Cloudinary.

Usage: python scripts/check_new_listings.py [--dry-run]
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


def _post_to_pending_platforms(conn, listing_id, url, image_urls, listing_caption):
    row = db.get(conn, listing_id)
    if not row["ig_posted"]:
        meta.post_to_instagram(image_urls, listing_caption)
        db.mark_posted(conn, listing_id, ig=True)
        conn.commit()
    if not row["fb_posted"]:
        meta.post_to_facebook(image_urls, listing_caption)
        db.mark_posted(conn, listing_id, fb=True)
        conn.commit()


def main():
    dry_run = "--dry-run" in sys.argv

    listings = sanity_client.fetch_listings()
    if not listings:
        print("No listings returned from Sanity — skipping.", file=sys.stderr)
        return

    conn = db.connect()

    if not db.is_bootstrapped(conn):
        for listing in listings:
            db.upsert_bootstrap(conn, listing)
        conn.commit()
        print(f"Bootstrapped database with {len(listings)} existing listings (no posts sent).")
        return

    known_ids = db.get_all_ids(conn)
    new_listings = [listing for listing in listings if listing["id"] not in known_ids]
    pending_rows = [
        row
        for row in (db.get(conn, listing_id) for listing_id in known_ids)
        if row and (not row["ig_posted"] or not row["fb_posted"])
    ]

    if not new_listings and not pending_rows:
        print("No new listings.")
        return

    for listing in new_listings:
        print(f"New listing: {listing['title']} ({listing['id']})")
        try:
            listing_caption = caption_mod.generate_caption(listing)
            transformed_images = images.transform_all(listing["images"])

            if dry_run:
                print("--- DRY RUN, not posting or saving ---")
                print("Caption:\n", listing_caption)
                print("Images:", transformed_images)
                continue

            db.upsert_new_listing(conn, listing, listing_caption, transformed_images)
            conn.commit()
            _post_to_pending_platforms(
                conn, listing["id"], listing["url"], transformed_images, listing_caption
            )
            print(f"Posted: {listing['title']}")
        except Exception:
            error = traceback.format_exc()
            print(error, file=sys.stderr)
            notify.send_error_email(
                subject=f"HomeShare social post failed: {listing['title']}",
                body=f"Listing: {listing['url']}\n\n{error}",
            )

    if dry_run:
        return

    for row in pending_rows:
        print(f"Retrying incomplete post: {row['title']} ({row['id']})")
        try:
            _post_to_pending_platforms(
                conn, row["id"], row["url"], json.loads(row["images"]), row["caption"]
            )
            print(f"Completed: {row['title']}")
        except Exception:
            error = traceback.format_exc()
            print(error, file=sys.stderr)
            notify.send_error_email(
                subject=f"HomeShare social post retry failed: {row['title']}",
                body=f"Listing: {row['url']}\n\n{error}",
            )


if __name__ == "__main__":
    main()
