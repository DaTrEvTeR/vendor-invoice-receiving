"""The JSON format of the invoicing network. All JSON vendors share it, so one parser serves them."""

from ..layouts import JsonLayout
from ..registry import register
from ..types import ParsedInvoice, SourceFile

INVOICE_JSON_V1 = JsonLayout(
    header={
        "document_type": "document_type",
        "vendor_name": "vendor.name",
        "invoice_number": "invoice_number",
        "invoice_date": "invoice_date",
        "currency": "currency",
        "po_reference": "po_reference",
        "subtotal": "subtotal",
        "tax": "tax",
        "total": "total",
        "notes": "notes",
        "references_invoice": "references_invoice",
    },
    line={
        "vendor_line_no": "line_no",
        "item_code": "item_code",
        "description": "description",
        "quantity": "quantity",
        "qty_backordered": "quantity_backordered",
        "uom": "uom",
        "unit_price": "unit_price",
        "amount": "amount",
        "serials": "serial_numbers",
    },
    charge={"item_code": "type", "amount": "amount"},
    required=frozenset(
        {"document_type", "invoice_number", "lines", "lines[].item_code", "lines[].quantity", "lines[].amount"}
    ),
    ignored=frozenset({"terms", "vendor.address"}),
)


@register("invoice_json_v1", detect=INVOICE_JSON_V1, priority=0)
def parse_invoice_json_v1(src: SourceFile) -> ParsedInvoice:
    """Parse a network JSON invoice, memo or credit memo."""
    return INVOICE_JSON_V1.parse(src)
