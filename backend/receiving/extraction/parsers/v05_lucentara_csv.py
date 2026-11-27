"""CSV export of Lucentara Gioielli (V05): Italian headers and notation, semicolon delimiter.

Numbers use a decimal comma and a dot for thousands ("1.125,00"); dates are day first
(04/05/2026 is 4 May, which also fits PO-2026-041 ordered on 2026-04-14). The invoice
total is a row labelled TOTALE rather than a column. The format's own words: the unit
PZ (pezzo, a piece) and the item code SPED (spedizione, shipping) of a charge row.
"""

from ...units import Unit
from ..layouts import CsvLayout
from ..registry import register
from ..types import ParsedInvoice, SourceFile
from ..values import ValueFormat

LUCENTARA_CSV = CsvLayout(
    delimiter=";",
    header={
        "invoice_number": "Numero",
        "invoice_date": "Data",
        "currency": "Valuta",
        "po_reference": "Rif. Ordine",
    },
    line={
        "item_code": "Codice",
        "description": "Descrizione",
        "quantity": "Q.ta",
        "uom": "U.M.",
        "unit_price": "Prezzo",
        "amount": "Importo",
    },
    values=ValueFormat(
        decimal_separator=",",
        thousands_separator=".",
        date_format="%d/%m/%Y",
        units={"PZ": Unit.EACH},
        charge_codes=frozenset({"SPED"}),
    ),
    total_row=("description", "TOTALE"),
)


@register("v05_lucentara_csv", detect=LUCENTARA_CSV, priority=10)
def parse_lucentara_csv(src: SourceFile) -> ParsedInvoice:
    """Parse a Lucentara CSV invoice."""
    return LUCENTARA_CSV.parse(src)
