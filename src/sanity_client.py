"""Read-only client for THE HomeShare's Sanity dataset.

The site (thehomeshare.ie) is an Eleventy static site backed by Sanity CMS —
there is no WordPress and no RSS feed. The "production" dataset is public for
reads (the site's own build process queries it with no auth token), so we
query it directly via HTTP instead of scraping HTML.
"""

import requests

PROJECT_ID = "gs4j2lbq"
DATASET = "production"
API_VERSION = "2024-01-01"
QUERY_URL = f"https://{PROJECT_ID}.api.sanity.io/v{API_VERSION}/data/query/{DATASET}"

APPLICATION_URL = "https://thehomeshare.ie/find-a-home-online-application-form/"

# _id is the permanent Sanity document id — stable across title/slug edits
# (e.g. when a listing's price changes and its slug is regenerated), so it's
# used as the primary key instead of the slug.
LISTINGS_QUERY = """
*[_type == "opportunity"] | order(dateListed desc) {
  "id": _id,
  title,
  "slug": slug.current,
  location,
  programme,
  gender,
  status,
  dateListed,
  "description": description[]{
    ...,
    "text": children[].text
  },
  "images": array::compact([coverImage.asset->url] + gallery[].asset->url)
}
"""


def _plain_text(description_blocks):
    if not description_blocks:
        return ""
    paragraphs = []
    for block in description_blocks:
        if block.get("_type") != "block":
            continue
        text = "".join(block.get("text") or [])
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def fetch_listings():
    """Return all opportunity listings currently published on the site."""
    response = requests.get(QUERY_URL, params={"query": LISTINGS_QUERY}, timeout=30)
    response.raise_for_status()
    raw = response.json()["result"]

    listings = []
    for item in raw:
        listings.append(
            {
                "id": item["id"],
                "title": item["title"],
                "slug": item.get("slug"),
                "url": f"https://thehomeshare.ie/opportunities/{item.get('slug')}/",
                "location": item.get("location"),
                "programme": item.get("programme") or "HomeSharing",
                "gender": item.get("gender") or "Either",
                "date_listed": item.get("dateListed") or "",
                "description": _plain_text(item.get("description")),
                "images": (item.get("images") or [])[:3],
            }
        )
    return listings
