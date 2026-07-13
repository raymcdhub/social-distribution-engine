"""Social media caption generation via OpenRouter (free-tier model).

Free-tier OpenRouter models are typically time-limited promotional listings
from the underlying inference provider, not permanent — expect to swap
DEFAULT_MODEL again in the future. Set OPENROUTER_MODEL to override without
a code change.
"""

import os
import time

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# openai/gpt-oss-120b:free — OpenAI's own open-weight release rather than a
# limited promotional checkpoint, chosen as a comparatively durable pick
# after meta-llama/llama-3.3-70b-instruct:free was retired (July 2026).
DEFAULT_MODEL = "openai/gpt-oss-120b:free"

PROMPT_TEMPLATE = """THE HomeShare facilitates homesharing arrangements, which are made up of two parties ( a sharer- a younger person (21 yo min) who needs an accommodation and needs to provide 10 hours per week of companionship and support. The older person, the householder, needs to live in their own house with some extra help from the sharer. so it's a mutually beneficial arrangement where everybody wins.
Consider this Instagram listing:
🏡 ROOM AVAILABLE — Delgany, Co. Wicklow
female sharer | 21+ | Animal lover | Non-smoker
✅ Double bedroom with private bathroom
✅ Shared kitchen & cosy sitting room
✅ Off-street parking
✅ Beautiful location in Delgany (A63)
🚌 25 mins by bus · 5 min drive to Delgany Village
🚙 15 min drive to Bray (~30 by bus)
🛣️ Easy M11 access to Dublin & Wicklow
💶 €355/month (in exchange for 10 hrs/week support & companionship)
👉 Apply at https://thehomeshare.ie/find-a-home-online-application-form/

Recreate this post using this new listing. If the new listing mentions Help4Housing, PLEASE DO ALSO. if the new listing mentions another price, PLEASE DO ALSO. Keep the format and tone, just change the relevant information about this new opportunity, just return the post caption ready to copy and paste. Note: the link never changes. The URL is always the same.

New listing:
Title: {title}
Location: {location}
Programme: {programme}
Gender preference: {gender}

Description:
{description}
"""


RETRY_STATUS_CODES = {429, 502, 503}
MAX_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 5


def generate_caption(listing):
    api_key = os.environ["OPENROUTER_API_KEY"]
    model = os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL
    prompt = PROMPT_TEMPLATE.format(
        title=listing["title"],
        location=listing["location"],
        programme=listing["programme"],
        gender=listing["gender"],
        description=listing["description"],
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/raymcdhub/social-distribution-engine",
                "X-Title": "THE HomeShare Social Distribution Engine",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
            timeout=60,
        )
        if response.ok:
            return response.json()["choices"][0]["message"]["content"].strip()

        if response.status_code in RETRY_STATUS_CODES and attempt < MAX_ATTEMPTS:
            wait = RETRY_BACKOFF_SECONDS * attempt
            print(f"OpenRouter {response.status_code}, retrying in {wait}s (attempt {attempt}/{MAX_ATTEMPTS})")
            time.sleep(wait)
            continue

        raise RuntimeError(
            f"OpenRouter API error {response.status_code} (model={model}): {response.text}"
        )
