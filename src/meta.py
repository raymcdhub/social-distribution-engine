"""Instagram + Facebook posting via the Meta Graph API."""

import json
import os
import time

import requests

GRAPH_URL = "https://graph.facebook.com/v19.0"


def _access_token():
    return os.environ["META_ACCESS_TOKEN"]


def _check(response):
    if not response.ok:
        raise RuntimeError(f"Meta Graph API error {response.status_code}: {response.text}")
    return response


MEDIA_FETCH_ERROR_SUBCODE = 2207052  # "Media download has failed" on a valid URL
MAX_MEDIA_FETCH_ATTEMPTS = 4
MEDIA_FETCH_RETRY_WAIT_SECONDS = 8

MEDIA_NOT_READY_SUBCODE = 2207027  # "Media ID is not available" at media_publish
MAX_PUBLISH_ATTEMPTS = 5
PUBLISH_RETRY_WAIT_SECONDS = 15


def _error_subcode(response):
    if response.status_code != 400:
        return None
    try:
        return response.json()["error"].get("error_subcode")
    except (ValueError, KeyError, TypeError):
        return None


def _is_media_fetch_error(response):
    return _error_subcode(response) == MEDIA_FETCH_ERROR_SUBCODE


def _post_fetching_media(url, data):
    """POST a Graph API call where Meta itself fetches a remote image (the
    image_url/url param). This step is intermittently flaky - it rejects a
    perfectly reachable URL with "Media download has failed" roughly every
    other post recently, on URLs that _warm() had just fetched successfully
    seconds earlier and that curl fetches fine afterwards too. Not caused
    by the image or by cold Cloudinary caching, so retry a few times with a
    short wait before giving up; any other error (bad token, wrong scopes,
    ...) still fails immediately as before."""
    last_response = None
    for attempt in range(1, MAX_MEDIA_FETCH_ATTEMPTS + 1):
        response = requests.post(url, data=data, timeout=30)
        if response.ok or not _is_media_fetch_error(response):
            return _check(response)
        last_response = response
        if attempt < MAX_MEDIA_FETCH_ATTEMPTS:
            print(
                f"Meta media-fetch error on attempt {attempt}/{MAX_MEDIA_FETCH_ATTEMPTS}, "
                f"retrying in {MEDIA_FETCH_RETRY_WAIT_SECONDS}s: {response.text}"
            )
            time.sleep(MEDIA_FETCH_RETRY_WAIT_SECONDS)
    return _check(last_response)


def _warm(image_urls, timeout=20):
    """Fetch each URL ourselves before handing it to Meta.

    Our images are unsigned Cloudinary "fetch" URLs, which transform the
    source image on demand the first time anything actually requests them.
    That first (cold) fetch+crop+reformat can take a couple of seconds,
    and Instagram's own media-download step times out and rejects the post
    with a generic "Media download has failed" error rather than waiting -
    seen in production on a repost whose URL hadn't been fetched by anyone
    since it was first generated. Warming here trades a few seconds in
    this job for Meta always hitting an already-cached copy.
    """
    for url in image_urls:
        try:
            requests.get(url, timeout=timeout)
        except requests.RequestException as exc:
            print(f"Warning: failed to pre-warm {url}: {exc}")


def _wait_until_finished(container_id, timeout=60, interval=3):
    """Poll an Instagram media container until Meta finishes processing it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = requests.get(
            f"{GRAPH_URL}/{container_id}",
            params={"fields": "status_code", "access_token": _access_token()},
            timeout=30,
        )
        _check(response)
        status = response.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram media container {container_id} failed to process")
        time.sleep(interval)
    raise TimeoutError(f"Instagram media container {container_id} did not finish in {timeout}s")


def post_to_instagram(image_urls, caption):
    ig_user_id = os.environ["META_IG_USER_ID"]
    token = _access_token()
    _warm(image_urls)

    if len(image_urls) == 1:
        response = _post_fetching_media(
            f"{GRAPH_URL}/{ig_user_id}/media",
            {"image_url": image_urls[0], "caption": caption, "access_token": token},
        )
        container_id = response.json()["id"]
        _wait_until_finished(container_id)
    else:
        child_ids = []
        for url in image_urls:
            response = _post_fetching_media(
                f"{GRAPH_URL}/{ig_user_id}/media",
                {"image_url": url, "is_carousel_item": "true", "access_token": token},
            )
            child_id = response.json()["id"]
            _wait_until_finished(child_id)
            child_ids.append(child_id)

        response = requests.post(
            f"{GRAPH_URL}/{ig_user_id}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": caption,
                "access_token": token,
            },
            timeout=30,
        )
        _check(response)
        container_id = response.json()["id"]
        _wait_until_finished(container_id)

    return _publish(ig_user_id, container_id, token)


def _publish(ig_user_id, container_id, token):
    """Publish a finished container. Instagram intermittently rejects this
    with "Media ID is not available" even though the container reported
    FINISHED moments earlier — it skipped Gouldavoher and Cashel's turns in
    Sept 2026 — so give it a little longer before giving up."""
    for attempt in range(1, MAX_PUBLISH_ATTEMPTS + 1):
        response = requests.post(
            f"{GRAPH_URL}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": token},
            timeout=30,
        )
        if response.ok or _error_subcode(response) != MEDIA_NOT_READY_SUBCODE:
            break
        if attempt < MAX_PUBLISH_ATTEMPTS:
            print(
                f"Instagram publish not ready on attempt {attempt}/{MAX_PUBLISH_ATTEMPTS}, "
                f"retrying in {PUBLISH_RETRY_WAIT_SECONDS}s: {response.text}"
            )
            time.sleep(PUBLISH_RETRY_WAIT_SECONDS)
    _check(response)
    return response.json()["id"]


def post_to_facebook(image_urls, caption):
    page_id = os.environ["META_PAGE_ID"]
    token = _access_token()
    _warm(image_urls)

    photo_ids = []
    for url in image_urls:
        response = _post_fetching_media(
            f"{GRAPH_URL}/{page_id}/photos",
            {"url": url, "published": "false", "access_token": token},
        )
        photo_ids.append(response.json()["id"])

    response = requests.post(
        f"{GRAPH_URL}/{page_id}/feed",
        data={
            "message": caption,
            "attached_media": json.dumps(
                [{"media_fbid": photo_id} for photo_id in photo_ids]
            ),
            "access_token": token,
        },
        timeout=30,
    )
    _check(response)
    return response.json()["id"]
