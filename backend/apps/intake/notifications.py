"""Email notifications for the intake flow.

Customer emails go out in the language of the request (``customer_*.es.txt``
templates for Spanish); emails to you are always English.

Every send is best-effort: a mail server hiccup is logged and never fails the
request that triggered it. Call these from ``transaction.on_commit`` so mail
only goes out for data that was actually saved.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone, translation

from . import pricing
from .i18n import normalize, t
from .models import RequestMessage, ServiceRequest

logger = logging.getLogger(__name__)

OWNER_LANGUAGE = "en"


def _context(req: ServiceRequest, language: str, **extra) -> dict:
    with translation.override(language):
        estimate = pricing.localize_estimate(req.estimate)
    return {
        "req": req,
        "estimate": estimate,
        "site_url": settings.SITE_URL,
        "business_name": getattr(settings, "BUSINESS_NAME", ""),
        **extra,
    }


def _template(base: str, language: str) -> str:
    """``customer_x.es.txt`` for Spanish, ``customer_x.txt`` for English."""
    return f"intake/email/{base}.txt" if language == "en" else f"intake/email/{base}.{language}.txt"


def _send(
    subject: str,
    template: str,
    context: dict,
    to: list[str],
    language: str,
    reply_to: list[str] | None = None,
) -> None:
    recipients = [address for address in to if address]
    if not recipients:
        return
    try:
        # Activating the language also localizes dates in the templates.
        with translation.override(language):
            body = render_to_string(_template(template, language), context).strip() + "\n"
        EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
            reply_to=[address for address in (reply_to or []) if address] or None,
        ).send()
    except Exception:  # noqa: BLE001 - never let email break a request
        logger.exception("Failed to send %s email", template)


def _owner_emails() -> list[str]:
    return list(settings.INTAKE_NOTIFY_EMAILS or [])


def _lang_query(language: str) -> str:
    return "" if language == "en" else f"?lang={language}"


def notify_new_request(req: ServiceRequest, claim_token: str | None = None) -> None:
    owner = OWNER_LANGUAGE
    kind = "booking" if req.request_type == ServiceRequest.RequestType.BOOKING else "callback"
    flag = t("email__subject--owner-emergency-flag", owner) if req.is_emergency else ""
    _send(
        t(f"email__subject--owner-new-{kind}", owner, id=req.id, name=req.name, flag=flag),
        "owner_new_request",
        _context(req, owner, language_label=t(f"email-language__label--{req.language}", owner)),
        _owner_emails(),
        owner,
        reply_to=[req.email],
    )
    language = normalize(req.language)
    claim_url = (
        f"{settings.SITE_URL}/claim/{claim_token}{_lang_query(language)}" if claim_token else None
    )
    _send(
        t("email__subject--customer-received", language, id=req.id),
        "customer_request_received",
        _context(req, language, claim_url=claim_url),
        [req.email],
        language,
        reply_to=_owner_emails(),
    )


def notify_customer_message(message: RequestMessage) -> None:
    req = message.request
    _send(
        t("email__subject--owner-customer-note", OWNER_LANGUAGE, name=req.name, id=req.id),
        "owner_customer_message",
        _context(req, OWNER_LANGUAGE, message=message),
        _owner_emails(),
        OWNER_LANGUAGE,
        reply_to=[req.email],
    )


def notify_staff_reply(message: RequestMessage) -> None:
    req = message.request
    language = normalize(req.language)
    _send(
        t("email__subject--customer-reply", language, id=req.id),
        "customer_staff_reply",
        _context(req, language, message=message),
        [req.email],
        language,
        reply_to=_owner_emails(),
    )


def notify_status_change(req: ServiceRequest) -> None:
    if req.status == ServiceRequest.Status.NEW:
        return
    language = normalize(req.language)
    scheduled_for = timezone.localtime(req.scheduled_for) if req.scheduled_for else None
    _send(
        t(
            "email__subject--customer-status",
            language,
            id=req.id,
            status=t(f"email-status__label--{req.status}", language),
        ),
        "customer_status_update",
        _context(
            req,
            language,
            headline=t(f"email-status__headline--{req.status}", language),
            scheduled_for=scheduled_for,
        ),
        [req.email],
        language,
        reply_to=_owner_emails(),
    )
