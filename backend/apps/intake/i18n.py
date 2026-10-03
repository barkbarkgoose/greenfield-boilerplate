"""Server-side text in English and Spanish.

Every customer-facing string the backend produces (service names, deals,
discount lines, validation errors, email subjects) lives in the text maps in
``text/en.json`` and ``text/es.json``, keyed BEM-style by where it shows up:
``block__element--modifier``, e.g. ``service__name--brake_pads``. The
frontend has its own maps for page copy; see the README's "Translations".

The request language comes from the browser's ``Accept-Language`` header
(Django's LocaleMiddleware). Long-form emails are separate templates per
language (``customer_*.es.txt``) rather than keys.

``apps/intake/test_i18n.py`` fails if a key is missing from either language,
is empty, uses different ``{placeholders}``, or isn't BEM-shaped.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from django.utils import translation

LANGUAGES = ("en", "es")
DEFAULT_LANGUAGE = "en"
TEXT_DIR = Path(__file__).parent / "text"


@lru_cache(maxsize=None)
def messages(language: str) -> dict[str, str]:
    with open(TEXT_DIR / f"{language}.json", encoding="utf-8") as handle:
        return json.load(handle)


def normalize(language: str | None) -> str:
    """Map a Django language code ("es-mx", "en-us", None) to "en" or "es"."""
    base = (language or "").split("-")[0].lower()
    return base if base in LANGUAGES else DEFAULT_LANGUAGE


def current_language() -> str:
    return normalize(translation.get_language())


def t(key: str, language: str | None = None, **params) -> str:
    """Text for ``key`` in ``language`` (default: the active request language)."""
    language = normalize(language) if language else current_language()
    text = messages(language).get(key) or messages(DEFAULT_LANGUAGE)[key]
    return text.format(**params) if params else text
