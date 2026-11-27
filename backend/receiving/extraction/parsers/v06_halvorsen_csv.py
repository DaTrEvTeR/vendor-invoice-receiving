"""CSV export of Halvorsen Silverworks (V06): upper-case headers, freight as its own row."""

from ..layouts import CsvLayout
from ..registry import register
from ..types import ParsedInvoice, SourceFile

HALVORSEN_CSV = CsvLayout(
    delimiter=",",
    header={
        "invoice_number": "INVOICE",
        "invoice_date": "DATE",
        "po_reference": "PO",
    },
    line={
        "item_code": "CODE",
        "description": "DESCRIPTION",
        "quantity": "QTY",
        "uom": "UM",
        "unit_price": "PRICE",
        "amount": "AMOUNT",
    },
)


@register("v06_halvorsen_csv", detect=HALVORSEN_CSV, priority=10)
def parse_halvorsen_csv(src: SourceFile) -> ParsedInvoice:
    """Parse a Halvorsen CSV invoice."""
    return HALVORSEN_CSV.parse(src)
