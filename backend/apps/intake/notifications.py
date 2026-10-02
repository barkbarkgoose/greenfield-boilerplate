"""Email notifications for the intake flow.

Every send is best-effort: a mail server hiccup is logged and never fails the
request that triggered it. Call these from ``transaction.on_commit`` so mail
only goes out for data that was actually saved.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone

from .models import RequestMessage, ServiceRequest

logger = logging.getLogger(__name__)

STATUS_HEADLINES = {
    ServiceRequest.Status.CONTACTED: "I'm looking into it and will be in touch.",
    ServiceRequest.Status.SCHEDULED: "your appointment is booked.",
    ServiceRequest.Status.COMPLETED: "the work is done. Thanks for your business!",
    ServiceRequest.Status.DECLINED: (
        "unfortunately this isn't a job I can take on. Sorry about that, and "
        "feel free to reach out for anything else."
    ),
}


def _context(req: ServiceRequest, **extra) -> dict:
    return {
        "req": req,
        "site_url": settings.SITE_URL,
        "business_name": getattr(settings, "BUSINESS_NAME", ""),
        **extra,
    }


def _send(subject: str, template: str, context: dict, to: list[str], reply_to: list[str] | None = None) -> None:
    recipients = [address for address in to if address]
    if not recipients:
        return
    try:
        body = render_to_string(f"intake/email/{template}", context).strip() + "\n"
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


def notify_new_request(req: ServiceRequest, claim_token: str | None = None) -> None:
    kind = "booking" if req.request_type == ServiceRequest.RequestType.BOOKING else "contact request"
    flag = " [EMERGENCY]" if req.is_emergency else ""
    _send(
        f"New {kind} #{req.id} from {req.name}{flag}",
        "owner_new_request.txt",
        _context(req),
        _owner_emails(),
        reply_to=[req.email],
    )
    claim_url = f"{settings.SITE_URL}/claim/{claim_token}" if claim_token else None
    _send(
        f"We got your request (#{req.id})",
        "customer_request_received.txt",
        _context(req, claim_url=claim_url),
        [req.email],
        reply_to=_owner_emails(),
    )


def notify_customer_message(message: RequestMessage) -> None:
    req = message.request
    _send(
        f"New note from {req.name} on #{req.id}",
        "owner_customer_message.txt",
        _context(req, message=message),
        _owner_emails(),
        reply_to=[req.email],
    )


def notify_staff_reply(message: RequestMessage) -> None:
    req = message.request
    _send(
        f"Reply about your request #{req.id}",
        "customer_staff_reply.txt",
        _context(req, message=message),
        [req.email],
        reply_to=_owner_emails(),
    )


def notify_status_change(req: ServiceRequest) -> None:
    headline = STATUS_HEADLINES.get(req.status)
    if not headline:
        return
    scheduled_for = timezone.localtime(req.scheduled_for) if req.scheduled_for else None
    _send(
        f"Request #{req.id}: {req.get_status_display()}",
        "customer_status_update.txt",
        _context(req, headline=headline, scheduled_for=scheduled_for),
        [req.email],
        reply_to=_owner_emails(),
    )
