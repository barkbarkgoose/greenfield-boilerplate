"""Verified invoices: what was actually delivered.

An invoice has two halves:

* **Material and loads** (``Invoice.items`` and ``Invoice.loads``), repriced by
  ``pricing.quote`` exactly like an order, so per-yard prices and per-load
  delivery fees follow the catalog. They start from the order's items and its
  dispatched loads; staff correct them to what really went out (an extra yard,
  a load that came from a farther yard...). Staff decide whether the rush fee
  applies (``charge_rush_fee``).
* **Lines** staff type in: services (spreading, a second dump spot), fees
  (wait time, a blocked driveway) and adjustments (a negative amount for a
  discount).

Customers see an invoice in their account only once it's published.
Publishing also sets the order's ``final_total`` to the invoice total.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import pricing
from .models import CENTS, Invoice, InvoiceLine, Order

LINE_KINDS = [kind.value for kind in InvoiceLine.Kind]


def _money(value: Decimal) -> str:
    return str(Decimal(value).quantize(CENTS))


def price(items: dict[str, int], loads: list[dict], charge_rush_fee: bool, today=None) -> dict:
    return pricing.quote(items, loads, None, today or timezone.localdate(), rush=charge_rush_fee)


def totals(priced: dict, lines: list[dict]) -> dict:
    """Sum an invoice. ``lines`` are dicts with kind, quantity and unit_price."""
    sums = {kind: Decimal(0) for kind in LINE_KINDS}
    for line in lines:
        amount = (Decimal(line["quantity"]) * Decimal(line["unit_price"])).quantize(CENTS)
        sums[line["kind"]] += amount
    delivered = Decimal(priced.get("total") or "0")
    total = delivered + sum(sums.values(), Decimal(0))
    return {
        "delivered": _money(delivered),
        "services": _money(sums["service"]),
        "fees": _money(sums["fee"]),
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


def _load_payload(load: dict) -> dict:
    return {"product": load["product"], "quantity": int(load["quantity"]), "miles": str(load["miles"])}


def payload(
    *,
    items: dict[str, int],
    loads: list[dict],
    charge_rush_fee: bool,
    priced: dict,
    lines: list[dict],
    note: str = "",
    invoice: Invoice | None = None,
) -> dict:
    """The API shape of an invoice, saved or not, with labels in the active language."""
    return {
        "exists": invoice is not None,
        "items": pricing.item_list(items),
        "loads": [_load_payload(load) for load in loads],
        "charge_rush_fee": charge_rush_fee,
        "priced": pricing.localize_quote(priced),
        "lines": [_line_payload(line) for line in lines],
        "note": note,
        "totals": totals(priced, lines),
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
        items=invoice.items,
        loads=invoice.loads,
        charge_rush_fee=invoice.charge_rush_fee,
        priced=invoice.priced,
        lines=_lines_of(invoice),
        note=invoice.note,
        invoice=invoice,
    )


def order_loads(order: Order) -> list[dict]:
    return [_load_payload({"product": l.product, "quantity": l.quantity, "miles": l.miles}) for l in order.loads.all()]


def draft_payload(order: Order) -> dict:
    """A starting point for an order with no invoice yet: what was ordered and planned."""
    items = dict(order.items or {})
    loads = order_loads(order)
    return payload(
        items=items,
        loads=loads,
        charge_rush_fee=order.is_rush,
        priced=price(items, loads, order.is_rush),
        lines=[],
    )


def _normalized(data: dict) -> tuple[dict, list[dict]]:
    items = pricing.normalize_quantities(data["items"], clamp=False)
    loads = [_load_payload(load) for load in data["loads"]]
    return items, loads


def preview(data: dict) -> dict:
    """Price validated invoice input without saving it."""
    items, loads = _normalized(data)
    return payload(
        items=items,
        loads=loads,
        charge_rush_fee=data["charge_rush_fee"],
        priced=price(items, loads, data["charge_rush_fee"]),
        lines=data["lines"],
        note=data.get("note", ""),
    )


def get_invoice(order: Order) -> Invoice | None:
    try:
        return order.invoice
    except Invoice.DoesNotExist:
        return None


@transaction.atomic
def save(order: Order, data: dict) -> tuple[Invoice, bool]:
    """Create or replace an order's invoice from validated input.

    Returns the invoice and whether this save published it (it wasn't before).
    """
    items, loads = _normalized(data)
    priced = price(items, loads, data["charge_rush_fee"])
    invoice = get_invoice(order) or Invoice(order=order)
    was_published = invoice.is_published

    invoice.items = items
    invoice.loads = loads
    invoice.charge_rush_fee = data["charge_rush_fee"]
    invoice.priced = priced
    invoice.note = data.get("note", "")
    invoice.total = Decimal(totals(priced, data["lines"])["total"])
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
    if order.final_total != final_total and (invoice.is_published or was_published):
        order.final_total = final_total
        order.save(update_fields=["final_total", "updated_at"])
    else:
        # Bump updated_at so a customer's open order page notices the change.
        order.save(update_fields=["updated_at"])
    return invoice, invoice.is_published and not was_published


@transaction.atomic
def delete(order: Order) -> None:
    invoice = get_invoice(order)
    if invoice is None:
        return
    if invoice.is_published:
        order.final_total = None
    invoice.delete()
    order.save(update_fields=["final_total", "updated_at"])
