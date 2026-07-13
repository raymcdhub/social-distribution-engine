"""Instagram + Facebook posting via the Meta Graph API."""

import json
import os
import time

import requests

GRAPH_URL = "https://graph.facebook.com/v19.0"


def _access_token():
    return os.environ["META_ACCESS_TOKEN"]


def _wait_until_finished(container_id, timeout=60, interval=3):
    """Poll an Instagram media container until Meta finishes processing it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = requests.get(
            f"{GRAPH_URL}/{container_id}",
            params={"fields": "status_code", "access_token": _access_token()},
            timeout=30,
        )
        response.raise_for_status()
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

    if len(image_urls) == 1:
        response = requests.post(
            f"{GRAPH_URL}/{ig_user_id}/media",
            data={"image_url": image_urls[0], "caption": caption, "access_token": token},
            timeout=30,
        )
        response.raise_for_status()
        container_id = response.json()["id"]
        _wait_until_finished(container_id)
    else:
        child_ids = []
        for url in image_urls:
            response = requests.post(
                f"{GRAPH_URL}/{ig_user_id}/media",
                data={"image_url": url, "is_carousel_item": "true", "access_token": token},
                timeout=30,
            )
            response.raise_for_status()
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
        response.raise_for_status()
        container_id = response.json()["id"]
        _wait_until_finished(container_id)

    response = requests.post(
        f"{GRAPH_URL}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["id"]


def post_to_facebook(image_urls, caption):
    page_id = os.environ["META_PAGE_ID"]
    token = _access_token()

    photo_ids = []
    for url in image_urls:
        response = requests.post(
            f"{GRAPH_URL}/{page_id}/photos",
            data={"url": url, "published": "false", "access_token": token},
            timeout=30,
        )
        response.raise_for_status()
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
    response.raise_for_status()
    return response.json()["id"]
