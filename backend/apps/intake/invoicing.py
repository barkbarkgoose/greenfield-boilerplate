"""Verified invoices: the work actually done and what the parts really cost.

An invoice has two halves:

* **Jobs** from the catalog (``Invoice.services``), repriced by
  ``pricing.estimate`` exactly like a booking, so bundles, free add-ons and the
  volume rate still apply when staff add or remove work. Staff decide whether
  the rush fee applies (``charge_rush_fee``).
* **Lines** staff type in: parts at what they actually paid (zero markup),
  shipping, extra labor (e.g. "other" work quoted by hand) and adjustments
  (a negative amount for a discount).

Customers see an invoice in their garage only once it's published. Publishing
also sets the request's ``final_total`` to the invoice total.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import pricing
from .models import CENTS, Invoice, InvoiceLine, ServiceRequest

LINE_KINDS = [kind.value for kind in InvoiceLine.Kind]


def _money(value: Decimal) -> str:
    return str(Decimal(value).quantize(CENTS))


def price_labor(services: dict[str, int], charge_rush_fee: bool, today=None) -> dict:
    return pricing.estimate(
        services, None, today or timezone.localdate(), emergency=charge_rush_fee
    )


def totals(labor: dict, lines: list[dict]) -> dict:
    """Sum an invoice. ``lines`` are dicts with kind, quantity and unit_price."""
    sums = {kind: Decimal(0) for kind in LINE_KINDS}
    for line in lines:
        amount = (Decimal(line["quantity"]) * Decimal(line["unit_price"])).quantize(CENTS)
        sums[line["kind"]] += amount
    jobs = Decimal(labor.get("total") or "0")
    total = jobs + sum(sums.values(), Decimal(0))
    return {
        "jobs": _money(jobs),
        "parts": _money(sums["part"]),
        "shipping": _money(sums["shipping"]),
        "labor": _money(sums["labor"]),
        "adjustments": _money(sums["adjustment"]),
        "total": _money(total),
    }


def _line_payload(line: dict) -> dict:
    quantity = Decimal(line["quantity"])
    unit_price = Decimal(line["unit_price"])
    return {
        "kind": line["kind"],
        "description": line["description"],
        # "2" rather than "2.00" for whole quantities.
        "quantity": format(quantity.normalize(), "f"),
        "unit_price": _money(unit_price),
        "amount": _money(quantity * unit_price),
    }


def payload(
    *,
    services: dict[str, int],
    charge_rush_fee: bool,
    labor: dict,
    lines: list[dict],
    note: str = "",
    invoice: Invoice | None = None,
) -> dict:
    """The API shape of an invoice, saved or not, with labels in the active language."""
    return {
        "exists": invoice is not None,
        "services": pricing.service_list(services),
        "charge_rush_fee": charge_rush_fee,
        "labor": pricing.localize_estimate(labor),
        "lines": [_line_payload(line) for line in lines],
        "note": note,
        "totals": totals(labor, lines),
        "published_at": invoice.published_at if invoice else None,
        "updated_at": invoice.updated_at if invoice else None,
    }


def _lines_of(invoice: Invoice) -> list[dict]:
    return [
        {
            "kind": line.kind,
            "description": line.description,
            "quantity": line.quantity,
            "unit_price": line.unit_price,
        }
        for line in invoice.lines.all()
    ]


def invoice_payload(invoice: Invoice) -> dict:
    return payload(
        services=invoice.services,
        charge_rush_fee=invoice.charge_rush_fee,
        labor=invoice.labor,
        lines=_lines_of(invoice),
        note=invoice.note,
        invoice=invoice,
    )


def draft_payload(req: ServiceRequest) -> dict:
    """A starting point for a request with no invoice yet: the requested jobs."""
    services = dict(req.services or {})
    return payload(
        services=services,
        charge_rush_fee=req.is_emergency,
        labor=price_labor(services, req.is_emergency),
        lines=[],
    )


def preview(data: dict) -> dict:
    """Price validated invoice input without saving it."""
    services = pricing.normalize_quantities(data["services"])
    return payload(
        services=services,
        charge_rush_fee=data["charge_rush_fee"],
        labor=price_labor(services, data["charge_rush_fee"]),
        lines=data["lines"],
        note=data.get("note", ""),
    )


def get_invoice(req: ServiceRequest) -> Invoice | None:
    try:
        return req.invoice
    except Invoice.DoesNotExist:
        return None


@transaction.atomic
def save(req: ServiceRequest, data: dict) -> tuple[Invoice, bool]:
    """Create or replace a request's invoice from validated input.

    Returns the invoice and whether this save published it (it wasn't before).
    """
    services = pricing.normalize_quantities(data["services"])
    labor = price_labor(services, data["charge_rush_fee"])
    invoice = get_invoice(req) or Invoice(request=req)
    was_published = invoice.is_published

    invoice.services = services
    invoice.charge_rush_fee = data["charge_rush_fee"]
    invoice.labor = labor
    invoice.note = data.get("note", "")
    invoice.total = Decimal(totals(labor, data["lines"])["total"])
    if data["published"] and not was_published:
        invoice.published_at = timezone.now()
    elif not data["published"]:
        invoice.published_at = None
    invoice.save()

    invoice.lines.all().delete()
    InvoiceLine.objects.bulk_create(
        InvoiceLine(
            invoice=invoice,
            kind=line["kind"],
            description=line["description"],
            quantity=line["quantity"],
            unit_price=line["unit_price"],
            position=index,
        )
        for index, line in enumerate(data["lines"])
    )

    # The published invoice *is* the final bill.
    final_total = invoice.total if invoice.is_published else None
    if req.final_total != final_total and (invoice.is_published or was_published):
        req.final_total = final_total
        req.save(update_fields=["final_total", "updated_at"])
    else:
        # Bump updated_at so a customer's open garage page notices the change.
        req.save(update_fields=["updated_at"])
    return invoice, invoice.is_published and not was_published


@transaction.atomic
def delete(req: ServiceRequest) -> None:
    invoice = get_invoice(req)
    if invoice is None:
        return
    if invoice.is_published:
        req.final_total = None
    invoice.delete()
    req.save(update_fields=["final_total", "updated_at"])
