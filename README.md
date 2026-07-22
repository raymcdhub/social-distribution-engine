# THE HomeShare Social Distribution Engine

Free, open-source rebuild of THE HomeShare's social media automation (previously
n8n + Railway) using Python + GitHub Actions — €0/month, full visibility of the code.

Twice a day, posts exactly one homesharing opportunity to Instagram and Facebook,
rotating fairly through every currently-live listing, and stops posting listings that
have been taken down.

## Why this needs to be a public repo

GitHub Actions minutes are only free without limit on **public** repositories. Private
repos get 2000 minutes/month included and are then billed — if the billing/payment
method has an issue, GitHub simply blocks every job from starting at all, rather than
running and charging. That's what took this repo down: it was private, and Actions
usage (an hourly backup schedule plus an external ~10-minute cron trigger) burned
through the free allotment. Keeping this repo public sidesteps the whole problem, and
costs nothing since `data/homeshare.db` only mirrors listing data that's already public
on `thehomeshare.ie` — no secrets live in the repo, only in Actions Secrets.

## How it works

**The site is not WordPress.** `thehomeshare.ie` is an Eleventy static site backed by
Sanity CMS (project `gs4j2lbq`, dataset `production`). There's no RSS feed to poll —
instead, `src/sanity_client.py` queries Sanity's public Content API directly with a
GROQ query (Sanity's query language — unrelated to the Groq AI inference company
below), the same way the site's own build process does. This gives structured data
(title, location, programme, gender, full description, image URLs) with no HTML
scraping and no auth token needed (the dataset is public-read).

### `scripts/post_cycle.py` — runs twice a day, posts exactly one listing

Triggered by GitHub's native `schedule` trigger only — no external cron service needed,
since twice a day tolerates GitHub's usual scheduling jitter fine (unlike a tight
~10-minute cadence, which GitHub's own scheduler can't reliably hit).

- **First run bootstraps**: seeds the database with every listing currently live,
  marked as already-posted, without sending anything — otherwise go-live would post
  all existing listings at once. After that, every run does the following, in order:

  1. **Mark delisted listings unavailable** — a listing is marked unavailable if its
     Sanity document id is no longer present in the live query results (i.e. it's been
     unpublished/deleted). Simpler and more reliable than checking each listing URL for
     a 404. This runs before posting so a listing removed today is never posted today.
  2. **Finish any incomplete post from a prior run** — if Instagram succeeded but
     Facebook errored (or vice versa) last time, this run retries only the platform
     that failed, using the already-generated caption/images. Takes priority over
     everything below so a stuck listing doesn't block the rotation forever.
  3. **Post the oldest brand-new listing**, if any listing exists on the site that
     isn't in the database yet. New listings jump to the front of the queue rather
     than waiting out a full rotation — generates a caption via OpenRouter (free tier)
     using the prompt/template in `src/caption.py`, transforms its images to
     Instagram's 4:5 ratio via Cloudinary (`src/images.py`, fetch-transform — no image
     bytes stored), and posts a carousel to Instagram and a multi-photo post to
     Facebook (`src/meta.py`).
  4. **Otherwise, repost whichever available listing was posted longest ago** — this
     round-robin rule is what guarantees fairness: no listing gets a second turn until
     every other active listing has had its next turn too. Reuses the stored
     caption/images (no regeneration).

  Only one of steps 2/3/4 fires per run (whichever applies first), so exactly one
  opportunity is posted per run — two per day, every listing's turn always comes.

## Setup

1. **Keep this repo public.** See "Why this needs to be a public repo" above — this is
   what keeps the whole thing free and immune to billing issues.
2. Add these repository secrets (Settings → Secrets and variables → Actions):
   - `OPENROUTER_API_KEY` — from https://openrouter.ai/keys. Defaults to
     `openai/gpt-oss-120b:free` (set in `src/caption.py`). **Free OpenRouter models
     are typically time-limited promotional listings, not permanent** — the original
     choice (`meta-llama/llama-3.3-70b-instruct:free`) was retired in July 2026 after
     a few weeks of use. When the current default is retired, either edit
     `DEFAULT_MODEL` in `src/caption.py`, or set the optional repository **variable**
     (Settings → Secrets and variables → Actions → *Variables* tab, not Secrets)
     `OPENROUTER_MODEL` to override it without a code change. Check
     https://openrouter.ai/models?max_price=0 for current free options.
   - `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`
   - `META_ACCESS_TOKEN` — long-lived Page access token with `instagram_basic`,
     `instagram_content_publish`, `pages_read_engagement`, `pages_manage_posts`.
     Refreshed manually (same as the previous n8n setup) — this token expires and
     there's no auto-refresh built in.
   - `META_PAGE_ID`, `META_IG_USER_ID`
   - `RESEND_API_KEY`, `EMAIL_FROM` (optional), `EMAIL_TO` — for failure alerts
3. Merge to the default branch — `post-cycle.yml` runs automatically on its own
   schedule (09:00 and 21:00 UTC), no external trigger or setup needed.

## Local testing

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY="..."
export CLOUDINARY_CLOUD_NAME="..." CLOUDINARY_API_KEY="..." CLOUDINARY_API_SECRET="..."
export META_ACCESS_TOKEN="..." META_PAGE_ID="..." META_IG_USER_ID="..."
export RESEND_API_KEY="..." EMAIL_TO="..."

# Bootstraps data/homeshare.db on first run (no posts sent)
python scripts/post_cycle.py

# Dry run: scrapes real data, calls OpenRouter + Cloudinary, but skips posting/DB writes
python scripts/post_cycle.py --dry-run
```

To simulate a "new listing" for a real end-to-end posting test, delete a row from
`data/homeshare.db` (`sqlite3 data/homeshare.db "DELETE FROM listings WHERE id = '...'"`)
and re-run `post_cycle.py` without `--dry-run`.

## Notes

- No image bytes are ever stored — Cloudinary's `fetch` delivery type transforms the
  Sanity-hosted image URL on the fly.
- `data/homeshare.db` is committed back to the repo by the workflow after each run,
  the same state-persistence pattern as the `utility` (email watcher) repo.
