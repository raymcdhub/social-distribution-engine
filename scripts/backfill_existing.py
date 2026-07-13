"""Admin/one-off: fix listings seeded by the initial bootstrap.

The bootstrap step (see check_new_listings.py) intentionally marks existing
listings as already-posted *without* generating real content, so go-live
doesn't blast every listing to social media at once. That leaves those rows
with an empty caption and un-transformed images — fine as long as they're
never actually reposted, but wrong the moment Algorithm 2 picks them up.

This script finds any available listing with an empty stored caption,
generates its real caption + Cloudinary-transformed images (without
posting), and staggers `last_posted_at` across the past N days so
Algorithm 2's daily run reposts them in batches over the next few days
instead of all landing on the same day once they cross the 4-day mark.

Usage: python scripts/backfill_existing.py
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import caption as caption_mod
import db
import images
import sanity_client

STAGGER_DAYS = [4, 3, 2, 1]  # first bucket is due immediately, last in 3 days
DELAY_BETWEEN_CALLS = 6  # seconds, to stay under OpenRouter's free-tier rate limit


def main():
    conn = db.connect()
    rows = [row for row in db.get_available(conn) if not row["caption"]]
    if not rows:
        print("No rows need backfilling.")
        return

    listings_by_id = {listing["id"]: listing for listing in sanity_client.fetch_listings()}

    bucket_size = -(-len(rows) // len(STAGGER_DAYS))  # ceil division
    now = datetime.now(timezone.utc)

    backfilled = 0
    for index, row in enumerate(rows):
        listing = listings_by_id.get(row["id"])
        if not listing:
            print(f"Skipping {row['id']} ({row['title']}) — no longer live on Sanity.")
            continue

        print(f"Backfilling: {row['title']} ({row['id']})")
        listing_caption = caption_mod.generate_caption(listing)
        transformed_images = images.transform_all(listing["images"])

        days_ago = STAGGER_DAYS[min(index // bucket_size, len(STAGGER_DAYS) - 1)]
        backdated_at = (now - timedelta(days=days_ago)).isoformat()

        conn.execute(
            "UPDATE listings SET caption = ?, images = ?, last_posted_at = ? WHERE id = ?",
            (listing_caption, json.dumps(transformed_images), backdated_at, row["id"]),
        )
        conn.commit()
        backfilled += 1
        time.sleep(DELAY_BETWEEN_CALLS)

    print(f"Backfilled {backfilled} listing(s).")


if __name__ == "__main__":
    main()
