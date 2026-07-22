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
# nvidia/nemotron-3-super-120b-a12b:free — openai/gpt-oss-120b:free and
# qwen/qwen3-next-80b-a3b-instruct:free (the previous default and first
# fallback) were both pulled from the free tier (404 "no longer available
# for free") as of July 2026. Check https://openrouter.ai/models?max_price=0
# for current free options when this one is eventually retired too.
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
# Free OpenRouter models share a global capacity pool per model, so a model
# can be temporarily saturated upstream regardless of your own usage — seen
# in practice on gpt-oss-120b:free during a 20-listing backfill. Falls back
# to a different free model (spread across different underlying providers,
# so one vendor pulling their free tier doesn't take out every fallback at
# once) rather than failing outright.
FALLBACK_MODELS = [
    "openai/gpt-oss-20b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
]

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
MAX_ATTEMPTS_PER_MODEL = 6
DEFAULT_BACKOFF_SECONDS = 10
MAX_BACKOFF_SECONDS = 30


def _retry_wait_seconds(response, attempt):
    """Prefer the server's own Retry-After guidance over a blind guess."""
    header_value = response.headers.get("Retry-After")
    if header_value:
        try:
            return min(float(header_value), MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    try:
        metadata_wait = response.json()["error"]["metadata"]["retry_after_seconds"]
        return min(float(metadata_wait), MAX_BACKOFF_SECONDS)
    except (ValueError, KeyError, TypeError):
        pass
    return min(DEFAULT_BACKOFF_SECONDS * attempt, MAX_BACKOFF_SECONDS)


def _call_model(model, prompt, api_key):
    """Try one model with retries. Returns caption text, or None if this
    model was exhausted (caller should try the next fallback model)."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS_PER_MODEL + 1):
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

        last_error = f"OpenRouter API error {response.status_code} (model={model}): {response.text}"
        if response.status_code in RETRY_STATUS_CODES and attempt < MAX_ATTEMPTS_PER_MODEL:
            wait = _retry_wait_seconds(response, attempt)
            print(f"OpenRouter {response.status_code} on {model}, retrying in {wait}s (attempt {attempt}/{MAX_ATTEMPTS_PER_MODEL})")
            time.sleep(wait)
            continue
        break

    print(f"Giving up on {model}: {last_error}")
    return None


def generate_caption(listing):
    api_key = os.environ["OPENROUTER_API_KEY"]
    requested_model = os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL
    models_to_try = [requested_model] + [m for m in FALLBACK_MODELS if m != requested_model]

    prompt = PROMPT_TEMPLATE.format(
        title=listing["title"],
        location=listing["location"],
        programme=listing["programme"],
        gender=listing["gender"],
        description=listing["description"],
    )

    for model in models_to_try:
        result = _call_model(model, prompt, api_key)
        if result is not None:
            return result

    raise RuntimeError(f"All OpenRouter models exhausted: {models_to_try}")
