"""Cloudinary fetch-transform of Sanity-hosted images to Instagram's 4:5 ratio.

Uses Cloudinary's "fetch" delivery type, which transforms a remote image on
the fly and serves it from Cloudinary's CDN without ever storing a copy or
re-uploading bytes — the source of truth stays the Sanity CDN URL.
"""

import os

import cloudinary
import cloudinary.utils

_configured = False


def _configure():
    global _configured
    if _configured:
        return
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
    )
    _configured = True


def transform_for_instagram(image_url):
    """Return a Cloudinary-fetched URL cropped to Instagram's 4:5 portrait ratio."""
    _configure()
    url, _ = cloudinary.utils.cloudinary_url(
        image_url,
        type="fetch",
        transformation=[
            {"aspect_ratio": "4:5", "crop": "fill", "gravity": "auto"},
            {"fetch_format": "auto", "quality": "auto"},
        ],
    )
    return url


def transform_all(image_urls):
    return [transform_for_instagram(url) for url in image_urls]
