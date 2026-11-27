"""CSV export of Thistlewood Fine Chains (V01): no unit column, freight and total on every row.

US notation: "2,085.00" and month-first dates (11/03/2026 is 3 November: the same
invoice 10482 arrives as JSON dated 2026-11-03).
"""

from ..layouts import CsvLayout
from ..registry import register
from ..types import ParsedInvoice, SourceFile
from ..values import ValueFormat

THISTLEWOOD_CSV = CsvLayout(
    delimiter=",",
    header={
        "invoice_number": "Invoice No",
        "invoice_date": "Invoice Date",
        "po_reference": "Customer PO",
        "total": "Invoice Total",
    },
    line={
        "item_code": "Item",
        "description": "Description",
        "quantity": "Qty",
        "unit_price": "Price",
        "amount": "Ext Price",
    },
    header_charges={"FREIGHT": "Freight"},
    values=ValueFormat(decimal_separator=".", thousands_separator=",", date_format="%m/%d/%Y"),
)


@register("v01_thistlewood_csv", detect=THISTLEWOOD_CSV, priority=10)
def parse_thistlewood_csv(src: SourceFile) -> ParsedInvoice:
    """Parse a Thistlewood CSV invoice."""
    return THISTLEWOOD_CSV.parse(src)
