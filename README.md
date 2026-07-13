# THE HomeShare Social Distribution Engine

Free, open-source rebuild of THE HomeShare's social media automation (previously
n8n + Railway) using Python + GitHub Actions — €0/month, full visibility of the code.

Automatically posts new homeshare listings to Instagram and Facebook, reposts active
listings every 4 days, and stops reposting listings that have been taken down.

## How it works

**The site is not WordPress.** `thehomeshare.ie` is an Eleventy static site backed by
Sanity CMS (project `gs4j2lbq`, dataset `production`). There's no RSS feed to poll —
instead, `src/sanity_client.py` queries Sanity's public Content API directly with a
GROQ query (Sanity's query language — unrelated to the Groq AI inference company
below), the same way the site's own build process does. This gives structured data
(title, location, programme, gender, full description, image URLs) with no HTML
scraping and no auth token needed (the dataset is public-read).

### Algorithm 1 — post on new listing (`scripts/check_new_listings.py`)

- **First run bootstraps**: seeds the database with every listing currently live,
  marked as already-posted, without sending anything — otherwise go-live would post
  all existing listings at once. After that, only genuinely new listings get posted.
- For each new listing: generates a caption via OpenRouter (Llama 3.3 70B, free tier)
  using the exact prompt/template in `src/caption.py`, transforms its images to Instagram's 4:5 ratio
  via Cloudinary (`src/images.py`, fetch-transform — no image bytes stored), posts a
  carousel to Instagram and a multi-photo post to Facebook (`src/meta.py`), and saves
  the listing to `data/homeshare.db`.
- Tracks `ig_posted`/`fb_posted` per listing so that if one platform fails (e.g.
  Instagram succeeds but Facebook errors), the next run retries only the platform that
  failed, using the already-generated caption/images — it won't regenerate or duplicate
  the successful post.
- Triggered by an external cron service (see setup below) roughly every 10 minutes,
  since GitHub's own `schedule` trigger is unreliable at that frequency (see the
  `utility` repo's README for why) — kept here only as an hourly backup.

### Algorithms 3 then 2 — daily maintenance (`scripts/daily_maintenance.py`)

Runs once daily, in this order so a listing removed today is never reposted today:

- **Algorithm 3** marks a listing unavailable if its Sanity document id is no longer
  present in the live query results (i.e. it's been unpublished/deleted) — simpler and
  more reliable than checking each listing URL for a 404.
- **Algorithm 2** reposts any still-available listing whose `last_posted_at` is 4+ days
  old, using its stored caption and images (no re-generation).

## Setup

1. Add these repository secrets (Settings → Secrets and variables → Actions):
   - `OPENROUTER_API_KEY` — from https://openrouter.ai/keys. The `meta-llama/llama-3.3-70b-instruct:free`
     model used by default costs nothing, but is rate-limited on OpenRouter's free
     tier; if you hit limits, swap the `MODEL` constant in `src/caption.py` for a
     paid model.
   - `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`
   - `META_ACCESS_TOKEN` — long-lived Page access token with `instagram_basic`,
     `instagram_content_publish`, `pages_read_engagement`, `pages_manage_posts`.
     Refreshed manually (same as the previous n8n setup) — this token expires and
     there's no auto-refresh built in.
   - `META_PAGE_ID`, `META_IG_USER_ID`
   - `RESEND_API_KEY`, `EMAIL_FROM` (optional), `EMAIL_TO` — for failure alerts
2. **Set up the reliable ~10-minute trigger** for `check-new-listings.yml` (same
   pattern used in the `utility` repo):
   1. Create a fine-grained PAT at
      https://github.com/settings/personal-access-tokens/new, scoped to only this
      repository, permission **Contents: Read and write**.
   2. At https://cron-job.org, create a job:
      - **URL**: `https://api.github.com/repos/<owner>/social-distribution-engine/dispatches`
      - **Method**: `POST`, every 10 minutes
      - **Headers**: `Authorization: Bearer <PAT>`,
        `Accept: application/vnd.github+json`,
        `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`
      - **Body**: `{"event_type": "check-new-listings"}`
3. Merge to the default branch — `daily-maintenance.yml` runs automatically on its
   own schedule; no external trigger needed since a repost every 4 days tolerates
   hours of jitter fine.

## Local testing

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY="..."
export CLOUDINARY_CLOUD_NAME="..." CLOUDINARY_API_KEY="..." CLOUDINARY_API_SECRET="..."
export META_ACCESS_TOKEN="..." META_PAGE_ID="..." META_IG_USER_ID="..."
export RESEND_API_KEY="..." EMAIL_TO="..."

# Bootstraps data/homeshare.db on first run (no posts sent)
python scripts/check_new_listings.py

# Dry run: scrapes real data, calls OpenRouter + Cloudinary, but skips posting/DB writes
python scripts/check_new_listings.py --dry-run

# Test daily maintenance (safe to run repeatedly)
python scripts/daily_maintenance.py --dry-run
```

To simulate a "new listing" for a real end-to-end posting test, delete a row from
`data/homeshare.db` (`sqlite3 data/homeshare.db "DELETE FROM listings WHERE id = '...'"`)
and re-run `check_new_listings.py` without `--dry-run`.

## Notes

- No image bytes are ever stored — Cloudinary's `fetch` delivery type transforms the
  Sanity-hosted image URL on the fly.
- `data/homeshare.db` is committed back to the repo by the workflow after each run,
  the same state-persistence pattern as the `utility` (email watcher) repo.
