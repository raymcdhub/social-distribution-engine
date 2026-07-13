"""Error alerts via Resend — same pattern as utility/check_opportunities.py."""

import os
import sys

import requests


def send_error_email(subject, body):
    api_key = os.environ.get("RESEND_API_KEY")
    email_to = os.environ.get("EMAIL_TO")
    if not api_key or not email_to:
        print(f"[notify] RESEND_API_KEY/EMAIL_TO not set, skipping email: {subject}", file=sys.stderr)
        return

    email_from = os.environ.get("EMAIL_FROM") or "Social Distribution Engine <onboarding@resend.dev>"

    response = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": email_from, "to": [email_to], "subject": subject, "text": body},
        timeout=30,
    )
    if not response.ok:
        print(f"Resend API error {response.status_code}: {response.text}", file=sys.stderr)
    response.raise_for_status()
