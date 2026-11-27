"""Checks: every reason an invoice needs a person (R1, R3, R6, M3, M8).

Validation never changes data. It reads the interpretation, the raw text and the
current state of POs and certificates, so running it again at approval time catches
anything that changed since upload. Comparisons are exact: there are no tolerances.
"""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .decimals import money, plain
from .extraction.types import DocumentType, LineType
from .matching import backorder_in_catalog_unit, convert_to_catalog, decimal_of, has_text, unit_given, unit_of
from .models import AuditEvent, Invoice, InvoiceLine, Issue, SerialUnit
from .units import GRAMS_PER_UNIT

Kind = Issue.Kind

# Order used in notes: what blocks most comes first.
SEVERITY = {Kind.TERMINAL: 0, Kind.HARD: 1, Kind.SOFT: 2, Kind.INFO: 3}


@dataclass(frozen=True)
class Finding:
    """One check result. Stored as an Issue row."""

    code: str
    kind: str
    message: str
    line: InvoiceLine | None = None


def by_severity(findings: list[Finding]) -> list[Finding]:
    """Findings ordered terminal, hard, soft, info (stable within a kind)."""
    return sorted(findings, key=lambda f: SEVERITY[f.kind])


def validate(invoice: Invoice) -> list[Finding]:
    """Run every check on a saved invoice."""
    if not invoice.raw_header:
        return [format_unrecognized(invoice)]
    lines = list(invoice.lines.select_related("product", "po_line__purchase_order").order_by("line_no"))
    return [
        *check_document(invoice),
        *check_header_values(invoice),
        *check_vendor_and_po(invoice),
        *check_lines(invoice, lines),
        *check_po_quantities(lines),
        *check_totals(invoice, lines),
    ]


def format_unrecognized(invoice: Invoice) -> Finding:
    """Nothing was extracted: the file can only be rejected (R9)."""
    upload = invoice.audit_events.filter(action=AuditEvent.Action.UPLOADED).first()
    error = (upload.payload.get("extraction_error") if upload else None) or {}
    reason = f"{error.get('message', 'the format is not recognized')} ({error.get('code', 'see logs')})"
    return Finding(
        "FORMAT_UNRECOGNIZED",
        Kind.TERMINAL,
        f"Nothing could be read from this file: {reason}. Reject it; once a parser supports the format, "
        "upload the file again.",
    )


def value_problem(label: str, raw: Any, line: InvoiceLine | None = None) -> Finding:
    """A required value that is unreadable (VALUE_UNPARSED) or absent (VALUE_MISSING)."""
    if has_text(raw):
        return Finding("VALUE_UNPARSED", Kind.HARD, f"{label} '{raw}' is not in an unambiguous format; enter it.", line)
    return Finding("VALUE_MISSING", Kind.HARD, f"{label} is missing; enter it.", line)


def is_receivable(invoice: Invoice) -> bool:
    """False for documents that are never received (R6); receipt-only checks skip them."""
    return invoice.document_type not in (DocumentType.MEMO, DocumentType.CREDIT_MEMO)


def check_document(invoice: Invoice) -> Iterator[Finding]:
    """Only an INVOICE can be received (R6)."""
    raw = invoice.raw_header
    if not invoice.document_type:
        yield value_problem("Document type", raw.get("document_type"))
    elif invoice.document_type == DocumentType.MEMO:
        yield Finding(
            "NOT_PURCHASE_INVOICE",
            Kind.TERMINAL,
            "MEMO: goods on consignment, the vendor keeps title. It is not a purchase invoice and is never "
            "received into stock; reject it or close it without receipt.",
        )
    elif invoice.document_type == DocumentType.CREDIT_MEMO:
        reference = invoice.parsed_header.get("references_invoice")
        about = f" for invoice {reference}" if reference else ""
        yield Finding(
            "NOT_PURCHASE_INVOICE",
            Kind.TERMINAL,
            f"CREDIT_MEMO{about}: a credit for returned goods never adds stock; reject it or close it without receipt.",
        )


def check_header_values(invoice: Invoice) -> Iterator[Finding]:
    """Header values that could not be read (R4)."""
    raw = invoice.raw_header
    if not invoice.invoice_number:
        yield value_problem("Invoice number", raw.get("invoice_number"))
    if invoice.invoice_date is None:
        yield value_problem("Invoice date", raw.get("invoice_date"))
    for name, label in (("subtotal", "Subtotal"), ("tax", "Tax"), ("total", "Total")):
        if getattr(invoice, name) is None and has_text(raw.get(name)):
            yield value_problem(label, raw.get(name))
    if not invoice.currency and has_text(raw.get("currency")):
        yield value_problem("Currency", raw.get("currency"))


def check_vendor_and_po(invoice: Invoice) -> Iterator[Finding]:
    """Vendor (M1), purchase order and currency (R7)."""
    po = invoice.purchase_order
    if invoice.vendor is None:
        name = invoice.parsed_header.get("vendor_name")
        detail = f"the vendor name '{name}' does not exactly match a known vendor" if name else "it names no vendor"
        yield Finding(
            "VENDOR_UNRESOLVED",
            Kind.HARD,
            f"Vendor could not be determined: the invoice has no known purchase order and {detail}; choose the vendor.",
        )
    if po is None:
        reference = invoice.parsed_header.get("po_reference")
        if reference and "purchase_order" not in invoice.edited_fields:
            yield Finding(
                "PO_NOT_FOUND", Kind.HARD, f"Purchase order '{reference}' does not exist; choose the right PO."
            )
        elif is_receivable(invoice):
            yield Finding(
                "PO_MISSING",
                Kind.SOFT,
                "The invoice references no purchase order; choose one, or accept receiving without a PO.",
            )
        return
    if invoice.vendor is not None and po.vendor_id != invoice.vendor_id:
        yield Finding(
            "PO_VENDOR_MISMATCH",
            Kind.HARD,
            f"{po.po_number} belongs to vendor {po.vendor_id}, but the invoice vendor is {invoice.vendor_id}.",
        )
    if invoice.currency and invoice.currency != po.currency:
        yield Finding(
            "CURRENCY_MISMATCH",
            Kind.SOFT,
            f"Invoice currency {invoice.currency} differs from {po.po_number} currency {po.currency}; "
            "amounts are not converted.",
        )


def check_lines(invoice: Invoice, lines: list[InvoiceLine]) -> Iterator[Finding]:
    """Per-line checks: mapping, quantity and unit, amounts, arithmetic, certificates, PO price."""
    seen_serials: set[str] = set()
    for line in lines:
        label = f"Line {line.line_no}"
        raw = line.raw
        if line.line_type == LineType.SUMMARY:
            description = line.parsed.get("description") or ""
            yield Finding(
                "SUMMARY_LINE",
                Kind.INFO,
                f"{label} ('{description}') has no item code and no quantity; it is shown for reference and "
                "neither received nor checked.",
                line,
            )
            continue
        if line.amount is None:
            yield value_problem(f"{label}: amount", raw.get("amount"), line)
        if line.line_type == LineType.CHARGE:
            continue

        unit_price = decimal_of(line.parsed, "unit_price")
        if unit_price is None and has_text(raw.get("unit_price")):
            yield Finding(
                "VALUE_UNPARSED",
                Kind.SOFT,
                f"{label}: unit price '{raw['unit_price']}' could not be read; the line arithmetic was not checked.",
                line,
            )
        vendor_qty = decimal_of(line.parsed, "quantity")
        if vendor_qty is not None and unit_price is not None and line.amount is not None:
            if vendor_qty * unit_price != line.amount:
                yield Finding(
                    "LINE_MATH_MISMATCH",
                    Kind.SOFT,
                    f"{label}: {plain(vendor_qty)} x {money(unit_price)} = {money(vendor_qty * unit_price)}, "
                    f"but the line amount is {money(line.amount)}.",
                    line,
                )

        if line.product is None:
            yield from unmapped_item(invoice, line, label)
            continue
        sku = line.product.sku
        if invoice.purchase_order is not None and line.po_line is None:
            yield Finding("NOT_ON_PO", Kind.SOFT, f"{label}: {sku} is not on {invoice.purchase_order_id}.", line)
        if is_receivable(invoice) and line.amount is not None and line.amount < 0:
            yield Finding(
                "AMOUNT_NEGATIVE",
                Kind.HARD,
                f"{label}: {sku} has a negative amount; stock cannot be received at a negative cost.",
                line,
            )
        if line.quantity is None:
            yield quantity_problem(line, label)
            continue
        if line.quantity <= 0:
            yield Finding(
                "QTY_NOT_POSITIVE",
                Kind.HARD,
                f"{label}: quantity {plain(line.quantity)} of {sku} is not positive.",
                line,
            )
        yield from unit_conversion(line, label)
        yield from unit_assumption(line, label)
        if line.product.serialized:
            yield from serial_problems(line, label, seen_serials)
        yield from price_problem(line, label)


def unmapped_item(invoice: Invoice, line: InvoiceLine, label: str) -> Iterator[Finding]:
    """The vendor's item code does not map to a SKU (no suggestions: R10)."""
    code = line.parsed.get("item_code")
    if not code:
        yield value_problem(f"{label}: item code", line.raw.get("item_code"), line)
    elif invoice.vendor is not None:
        description = line.parsed.get("description")
        about = f" ({description})" if description else ""
        yield Finding(
            "SKU_UNMAPPED",
            Kind.HARD,
            f"{label}: vendor item code '{code}'{about} is not mapped to a store SKU for {invoice.vendor_id}; "
            "choose the SKU.",
            line,
        )


def quantity_problem(line: InvoiceLine, label: str) -> Finding:
    """Why the quantity in the catalog unit could not be derived (R2)."""
    raw = line.raw
    target = line.product.unit
    if decimal_of(line.parsed, "quantity") is None:
        return value_problem(f"{label}: quantity", raw.get("quantity"), line)
    conversion = convert_to_catalog(line)
    if conversion is not None:  # convertible, but the result does not fit storage precision
        return Finding(
            "VALUE_OUT_OF_RANGE",
            Kind.HARD,
            f"{label}: {raw['quantity']} {conversion.from_unit} is {plain(conversion.quantity)} {target}, more than "
            "can be stored exactly; enter the quantity.",
            line,
        )
    if unit_of(line.parsed) is None:
        return Finding(
            "UOM_UNKNOWN",
            Kind.HARD,
            f"{label}: unit '{raw['uom']}' is not a known unit of measure; enter the quantity of "
            f"{line.product.sku} in {target}.",
            line,
        )
    return Finding(
        "UOM_MISMATCH",
        Kind.HARD,
        f"{label}: '{raw['uom']}' cannot be converted to {target}, the catalog unit of {line.product.sku}; "
        f"enter the quantity in {target}.",
        line,
    )


def unit_conversion(line: InvoiceLine, label: str) -> Iterator[Finding]:
    """Report a unit conversion; flag it when rounding was needed (R2)."""
    if "quantity" in line.edited_fields:
        return
    conversion = convert_to_catalog(line)
    if conversion is None or not conversion.changed_unit:
        return
    if conversion.exact:
        factor = GRAMS_PER_UNIT[conversion.from_unit] / GRAMS_PER_UNIT[conversion.to_unit]
        yield Finding(
            "UNIT_CONVERTED",
            Kind.INFO,
            f"{label}: {line.raw['quantity']} {line.raw['uom']} converted to {plain(conversion.quantity)} "
            f"{conversion.to_unit} (1 {conversion.from_unit} = {plain(factor)} {conversion.to_unit}).",
            line,
        )
    else:
        yield Finding(
            "CONVERSION_ROUNDED",
            Kind.SOFT,
            f"{label}: {line.raw['quantity']} {line.raw['uom']} is not a whole number of 0.000001 "
            f"{conversion.to_unit}; rounded to {plain(conversion.quantity)}. Confirm or enter the quantity.",
            line,
        )


def unit_assumption(line: InvoiceLine, label: str) -> Iterator[Finding]:
    """No unit stated: the quantity was taken in the SKU's unit (matching.vendor_unit).

    The assumption stands on its own only when the PO price confirms it exactly
    (amount == quantity x PO unit cost); otherwise a person confirms it.
    """
    if unit_given(line) or "quantity" in line.edited_fields:
        return
    sku, unit, quantity = line.product.sku, line.product.unit, plain(line.quantity)
    po_line = line.po_line
    if po_line is not None and line.amount is not None and line.amount == line.quantity * po_line.unit_cost:
        yield Finding(
            "UNIT_ASSUMED",
            Kind.INFO,
            f"{label}: no unit of measure given; {quantity} taken as {unit}, the unit of {sku}, which the PO price "
            "confirms.",
            line,
        )
    else:
        yield Finding(
            "UNIT_ASSUMED",
            Kind.SOFT,
            f"{label}: no unit of measure given; {quantity} taken as {unit}, the unit of {sku}, but no PO price "
            f"confirms it. Confirm, or enter the quantity in {unit}.",
            line,
        )


def serial_problems(line: InvoiceLine, label: str, seen: set[str]) -> Iterator[Finding]:
    """Each serialized item needs exactly one new certificate number (M8)."""
    sku = line.product.sku
    serials = list(line.serials)
    if Decimal(len(serials)) != line.quantity:
        yield Finding(
            "SERIAL_COUNT_MISMATCH",
            Kind.HARD,
            f"{label}: {sku} is serialized; quantity is {plain(line.quantity)} but {len(serials)} certificate "
            "number(s) are given. Enter the missing numbers or correct the quantity.",
            line,
        )
    repeated = sorted({s for s in serials if serials.count(s) > 1} | (set(serials) & seen))
    in_stock = sorted(SerialUnit.objects.filter(serial_number__in=serials).values_list("serial_number", flat=True))
    seen.update(serials)
    if repeated:
        yield Finding(
            "SERIAL_DUPLICATE",
            Kind.HARD,
            f"{label}: certificate number(s) {', '.join(repeated)} appear more than once on this invoice.",
            line,
        )
    if in_stock:
        yield Finding(
            "SERIAL_DUPLICATE",
            Kind.HARD,
            f"{label}: certificate number(s) {', '.join(in_stock)} were already received.",
            line,
        )


def price_problem(line: InvoiceLine, label: str) -> Iterator[Finding]:
    """The line amount equals the PO price exactly (R3): amount == quantity x unit cost."""
    if line.po_line is None or line.amount is None:
        return
    sku = line.product.sku
    expected = line.quantity * line.po_line.unit_cost
    if line.amount != expected:
        yield Finding(
            "PRICE_MISMATCH",
            Kind.SOFT,
            f"{label}: invoice amount {money(line.amount)} for {sku} differs from the PO price: "
            f"{plain(line.quantity)} {line.product.unit} x {money(line.po_line.unit_cost)} = {money(expected)}.",
            line,
        )


def check_po_quantities(lines: list[InvoiceLine]) -> Iterator[Finding]:
    """Quantities against what is still open on each PO line (M3)."""
    groups: dict[int, list[InvoiceLine]] = defaultdict(list)
    for line in lines:
        if line.line_type == LineType.PRODUCT and line.po_line is not None and line.quantity is not None:
            groups[line.po_line_id].append(line)
    for group in groups.values():
        first, po_line = group[0], group[0].po_line
        label = f"Line {first.line_no}"
        sku, unit, po = po_line.product_id, first.product.unit, po_line.purchase_order_id
        shipped = sum((line.quantity for line in group), Decimal("0"))
        remaining = po_line.remaining
        if shipped > remaining:
            yield Finding(
                "OVER_RECEIPT",
                Kind.SOFT,
                f"{label}: {plain(shipped)} {unit} of {sku} exceeds the {plain(max(remaining, Decimal('0')))} "
                f"still open on {po}.",
                first,
            )
        elif shipped < remaining:
            backorders = [backorder_in_catalog_unit(line) for line in group]
            backorder = None if None in backorders else sum(backorders, Decimal("0"))
            if backorder is not None and shipped + backorder == remaining:
                yield Finding(
                    "PARTIAL_SHIPMENT",
                    Kind.INFO,
                    f"{label}: partial shipment of {sku}, {plain(shipped)} of {plain(remaining)} {unit} open on {po}; "
                    f"the vendor reports {plain(backorder)} on backorder.",
                    first,
                )
            else:
                reason = (
                    f"the reported backorder of {plain(backorder)} does not account for the difference"
                    if backorder is not None
                    else "the invoice reports no backorder"
                )
                yield Finding(
                    "SHORT_SHIPMENT",
                    Kind.SOFT,
                    f"{label}: {plain(shipped)} {unit} of {sku} is less than the {plain(remaining)} open on {po}, "
                    f"and {reason}.",
                    first,
                )


def check_totals(invoice: Invoice, lines: list[InvoiceLine]) -> Iterator[Finding]:
    """Subtotal, charges, tax and total reconcile exactly with the lines (R3)."""
    amounts = [line.amount for line in lines if line.line_type != LineType.SUMMARY]
    if None in amounts:
        return  # a line amount is still unknown; already reported
    goods = sum((line.amount for line in lines if line.line_type == LineType.PRODUCT), Decimal("0"))
    charges = sum((line.amount for line in lines if line.line_type == LineType.CHARGE), Decimal("0"))
    subtotal, tax, total = invoice.subtotal, invoice.tax, invoice.total
    raw = invoice.raw_header
    if subtotal is None and total is None:
        if not has_text(raw.get("subtotal")) and not has_text(raw.get("total")):
            yield Finding(
                "TOTALS_ABSENT",
                Kind.INFO,
                "The invoice states no subtotal or total; only the line arithmetic was checked.",
            )
        return
    if subtotal is not None and goods != subtotal:
        yield Finding(
            "TOTALS_MISMATCH",
            Kind.SOFT,
            f"Header totals do not reconcile: lines sum to {money(goods)}, invoice subtotal is {money(subtotal)}.",
        )
    if total is not None:
        base = subtotal if subtotal is not None else goods
        expected = base + charges + (tax or Decimal("0"))
        if expected != total:
            what = "subtotal" if subtotal is not None else "lines"
            yield Finding(
                "TOTALS_MISMATCH",
                Kind.SOFT,
                f"Invoice total {money(total)} does not equal {what} {money(base)} + charges {money(charges)} "
                f"+ tax {money(tax or Decimal('0'))} = {money(expected)}.",
            )
