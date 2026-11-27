"""Transform: derive the system's interpretation from what the parser read (M1, R2, R7).

Every interpretation field is computed from the parsed values plus reference data,
except the fields a person has edited (listed in `edited_fields`), which are kept as
they are. The same code runs at upload and after every edit, so there is exactly one
way an invoice gets interpreted. Matching is exact only: no fuzzy matching (R10).
"""

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from .decimals import fits_storage
from .extraction.types import LineType
from .models import Invoice, InvoiceLine, POLine, Product, PurchaseOrder, Vendor, VendorItem
from .units import Conversion, Unit, convert


def assign(obj: Invoice | InvoiceLine, field: str, value: Any) -> None:
    """Set an interpretation field unless a person has edited it."""
    if field not in obj.edited_fields:
        setattr(obj, field, value)


def has_text(value: Any) -> bool:
    """True when a raw value holds something other than whitespace."""
    return isinstance(value, str) and bool(value.strip())


def decimal_of(values: Mapping[str, Any], field: str) -> Decimal | None:
    """A parsed decimal (stored as exact text), or None."""
    value = values.get(field)
    return Decimal(value) if value is not None else None


def date_of(values: Mapping[str, Any], field: str) -> date | None:
    """A parsed date (stored as ISO text), or None."""
    value = values.get(field)
    return date.fromisoformat(value) if value is not None else None


def unit_of(values: Mapping[str, Any]) -> Unit | None:
    """The parsed vendor unit, if it was an exact known alias."""
    value = values.get("uom")
    return Unit(value) if value is not None else None


def resolve_purchase_order(parsed_header: Mapping[str, Any]) -> PurchaseOrder | None:
    """The PO whose number exactly equals the invoice's PO reference."""
    number = parsed_header.get("po_reference")
    return PurchaseOrder.objects.select_related("vendor").filter(pk=number).first() if number else None


def resolve_vendor(invoice: Invoice) -> Vendor | None:
    """M1: the PO's vendor. Without a PO, the one vendor whose name is exactly the invoice's."""
    if invoice.purchase_order is not None:
        return invoice.purchase_order.vendor
    name = invoice.parsed_header.get("vendor_name")
    if not name:
        return None
    matches = list(Vendor.objects.filter(name=name)[:2])
    return matches[0] if len(matches) == 1 else None


def resolve_currency(invoice: Invoice) -> str:
    """The invoice's own currency; for a format without one, the vendor's (R7)."""
    if has_text(invoice.raw_header.get("currency")):
        return invoice.parsed_header.get("currency") or ""  # unreadable text goes to a person
    return invoice.vendor.currency if invoice.vendor else ""


def resolve_product(vendor: Vendor | None, parsed: Mapping[str, Any]) -> Product | None:
    """The SKU mapped to the vendor's item code, exact match only."""
    code = parsed.get("item_code")
    if vendor is None or not code:
        return None
    item = VendorItem.objects.select_related("product").filter(vendor=vendor, vendor_item_code=code).first()
    return item.product if item else None


def unit_given(line: InvoiceLine) -> bool:
    """Whether the vendor states a unit at all (a format may have no unit field, or leave it blank)."""
    return has_text(line.raw.get("uom"))


def vendor_unit(line: InvoiceLine) -> Unit | None:
    """The unit of the vendor's quantity.

    With no unit stated, the SKU's own catalog unit is assumed. Validation lets that
    stand on its own only when the PO price confirms it exactly; otherwise a person
    confirms it. A unit that is stated but unknown is never replaced.
    """
    if not unit_given(line):
        return Unit(line.product.unit) if line.product else None
    return unit_of(line.parsed)


def convert_to_catalog(line: InvoiceLine, field: str = "quantity") -> Conversion | None:
    """A vendor quantity field converted to the product's catalog unit, when everything is known."""
    quantity = decimal_of(line.parsed, field)
    unit = vendor_unit(line)
    if line.product is None or quantity is None or unit is None:
        return None
    return convert(quantity, unit, Unit(line.product.unit))


def resolve_po_line(purchase_order: PurchaseOrder | None, product: Product | None) -> POLine | None:
    """The PO line for this SKU on the invoice's PO."""
    if purchase_order is None or product is None:
        return None
    return (
        POLine.objects.select_related("purchase_order").filter(purchase_order=purchase_order, product=product).first()
    )


def interpret(invoice: Invoice, lines: Iterable[InvoiceLine]) -> None:
    """Fill every non-edited interpretation field of the invoice and its lines (not saved)."""
    values = invoice.parsed_header
    assign(invoice, "document_type", values.get("document_type") or "")
    assign(invoice, "invoice_number", values.get("invoice_number") or "")
    assign(invoice, "invoice_date", date_of(values, "invoice_date"))
    assign(invoice, "purchase_order", resolve_purchase_order(values))
    assign(invoice, "vendor", resolve_vendor(invoice))
    assign(invoice, "currency", resolve_currency(invoice))
    for name in ("subtotal", "tax", "total"):
        assign(invoice, name, decimal_of(values, name))
    invoice.notes = invoice.raw_header.get("notes") or ""
    for line in lines:
        interpret_line(invoice, line)


def interpret_line(invoice: Invoice, line: InvoiceLine) -> None:
    """Fill the line's non-edited interpretation fields. Only product lines map to stock."""
    assign(line, "line_type", line.parsed.get("line_type", line.line_type))
    assign(line, "amount", decimal_of(line.parsed, "amount"))
    if line.line_type != LineType.PRODUCT:
        line.product = line.po_line = line.quantity = None
        line.serials = []
        return
    assign(line, "product", resolve_product(invoice.vendor, line.parsed))
    conversion = convert_to_catalog(line)
    fits = conversion is not None and fits_storage(conversion.quantity)
    assign(line, "quantity", conversion.quantity if fits else None)  # too large to store exactly: a person decides
    assign(line, "serials", list(line.parsed.get("serials", [])))
    line.po_line = resolve_po_line(invoice.purchase_order, line.product)


def backorder_in_catalog_unit(line: InvoiceLine) -> Decimal | None:
    """The vendor's backorder quantity in the catalog unit, only when exact."""
    conversion = convert_to_catalog(line, "qty_backordered")
    return conversion.quantity if conversion and conversion.exact else None
