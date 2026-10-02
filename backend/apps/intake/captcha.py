"""Spam protection for public forms: Cloudflare Turnstile plus a honeypot.

Turnstile is enabled only when ``TURNSTILE_SECRET_KEY`` is configured, so local
development and tests run without it. The honeypot is always on: the forms
render a visually hidden ``website`` field that people never fill in.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from rest_framework import serializers

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
HONEYPOT_FIELD = "website"


def captcha_enabled() -> bool:
    return bool(getattr(settings, "TURNSTILE_SECRET_KEY", ""))


def verify_turnstile(token: str, remote_ip: str | None = None) -> bool:
    payload = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip
    request = urllib.request.Request(
        VERIFY_URL, data=urllib.parse.urlencode(payload).encode(), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError):
        logger.warning("Turnstile verification request failed", exc_info=True)
        return False
    return bool(body.get("success"))


def check_human(request) -> None:
    """Raise a 400 ValidationError if the submission looks automated."""
    if str(request.data.get(HONEYPOT_FIELD) or "").strip():
        raise serializers.ValidationError({"detail": "Submission rejected."})
    if not captcha_enabled():
        return
    token = str(request.data.get("captcha_token") or "")
    if not token or not verify_turnstile(token, request.META.get("REMOTE_ADDR")):
        raise serializers.ValidationError(
            {"captcha_token": "Please complete the verification and try again."}
        )
