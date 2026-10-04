"""Email notifications for orders.

Customer emails go out in the language of the order (``customer_*.es.txt``
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
from django.utils import translation

from . import pricing, service_area
from .i18n import normalize, t
from .models import Order, OrderMessage

logger = logging.getLogger(__name__)

OWNER_LANGUAGE = "en"


def _context(order: Order, language: str, **extra) -> dict:
    with translation.override(language):
        quote = pricing.localize_quote(order.quote)
    return {
        "order": order,
        "quote": quote,
        "window_label": t(f"delivery-window__label--{order.delivery_window}", language),
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


def notify_new_order(order: Order, claim_token: str | None = None) -> None:
    owner = OWNER_LANGUAGE
    kind = "delivery" if order.request_type == Order.RequestType.DELIVERY else "callback"
    flag = t("email__subject--owner-rush-flag", owner) if order.is_rush else ""
    if order.plan_status in (Order.PlanStatus.NO_CAPACITY, Order.PlanStatus.OUT_OF_STOCK):
        flag += t("email__subject--owner-dispatch-flag", owner)
    _send(
        t(f"email__subject--owner-new-{kind}", owner, id=order.id, name=order.name, flag=flag),
        "owner_new_order",
        _context(
            order,
            owner,
            language_label=t(f"email-language__label--{order.language}", owner),
            city=service_area.lookup(order.zip_code).city if order.zip_code else "",
            loads=list(order.loads.select_related("yard", "truck")),
        ),
        _owner_emails(),
        owner,
        reply_to=[order.email],
    )
    language = normalize(order.language)
    claim_url = f"{settings.SITE_URL}/claim/{claim_token}{_lang_query(language)}" if claim_token else None
    _send(
        t("email__subject--customer-received", language, id=order.id),
        "customer_order_received",
        _context(order, language, claim_url=claim_url),
        [order.email],
        language,
        reply_to=_owner_emails(),
    )


def notify_customer_message(message: OrderMessage) -> None:
    order = message.order
    _send(
        t("email__subject--owner-customer-note", OWNER_LANGUAGE, name=order.name, id=order.id),
        "owner_customer_message",
        _context(order, OWNER_LANGUAGE, message=message),
        _owner_emails(),
        OWNER_LANGUAGE,
        reply_to=[order.email],
    )


def notify_staff_reply(message: OrderMessage) -> None:
    order = message.order
    language = normalize(order.language)
    _send(
        t("email__subject--customer-reply", language, id=order.id),
        "customer_staff_reply",
        _context(order, language, message=message),
        [order.email],
        language,
        reply_to=_owner_emails(),
    )


def notify_status_change(order: Order) -> None:
    if order.status == Order.Status.NEW:
        return
    language = normalize(order.language)
    _send(
        t(
            "email__subject--customer-status",
            language,
            id=order.id,
            status=t(f"email-status__label--{order.status}", language),
        ),
        "customer_status_update",
        _context(order, language, headline=t(f"email-status__headline--{order.status}", language)),
        [order.email],
        language,
        reply_to=_owner_emails(),
    )


def notify_password_reset(user, reset_url: str, language: str) -> None:
    """Send a password reset link in the language it was requested in."""
    language = normalize(language)
    _send(
        t("email__subject--password-reset", language, business=settings.BUSINESS_NAME),
        "customer_password_reset",
        {
            "name": user.name,
            "reset_url": reset_url,
            "hours": settings.PASSWORD_RESET_TIMEOUT // 3600,
            "business_name": getattr(settings, "BUSINESS_NAME", ""),
        },
        [user.email],
        language,
    )


def notify_invoice(order: Order) -> None:
    """Send the customer their invoice once it's published."""
    from . import invoicing  # invoicing -> models; keep import-time cycles out

    invoice = invoicing.get_invoice(order)
    if invoice is None or not invoice.is_published:
        return
    language = normalize(order.language)
    with translation.override(language):
        data = invoicing.invoice_payload(invoice)
    lines = [
        {**line, "kind_label": t(f"email-invoice__kind--{line['kind']}", language)}
        for line in data["lines"]
    ]
    _send(
        t("email__subject--customer-invoice", language, id=order.id),
        "customer_invoice",
        _context(order, language, invoice=data, priced=data["priced"], lines=lines),
        [order.email],
        language,
        reply_to=_owner_emails(),
    )
