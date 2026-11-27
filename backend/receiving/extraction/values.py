"""Strict value parsing (R4).

Every file format declares how it writes values (a ValueFormat): numbers, dates and
its own words for units and charge rows. A value is accepted only when it matches
that declaration exactly. Lucentara writes "1.125,00", "04/05/2026" (day first) and
"PZ" for pieces, Thistlewood "2,085.00" and "11/03/2026" (month first); the same text
in a format that declares otherwise is not guessed: it stays unparsed, its text is
kept, and a person enters the value during review.
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from functools import cached_property
from typing import Any

from ..decimals import fits_storage
from ..units import Unit, unit_from_alias
from .types import ABSENT, DocumentType, RawValue

_CURRENCY = re.compile(r"[A-Z]{3}")

# Marks a field that is not present in the source record at all.
MISSING: Any = object()


@dataclass(frozen=True)
class ValueFormat:
    """How a file format writes values. Each layout declares its own."""

    decimal_separator: str = "."
    thousands_separator: str | None = None
    date_format: str = "%Y-%m-%d"
    # The format's own words, on top of the shared English ones (UOM_ALIASES, CHARGE_CODES).
    units: Mapping[str, Unit] = field(default_factory=dict)  # upper-case unit word -> unit
    charge_codes: frozenset[str] = frozenset()  # upper-case item codes of charge rows

    @cached_property
    def number_pattern(self) -> re.Pattern[str]:
        """Exactly the number notation of this format: optional sign, grouped or plain digits, fraction."""
        integer = r"\d+"
        if self.thousands_separator:
            group = re.escape(self.thousands_separator)
            integer = rf"(?:\d{{1,3}}(?:{group}\d{{3}})+|\d+)"
        return re.compile(rf"-?{integer}(?:{re.escape(self.decimal_separator)}\d+)?")


PLAIN = ValueFormat()  # 1234.56 and ISO dates: JSON, and CSVs that use them


def to_raw(value: Any) -> str:
    """The text of a source value. JSON null becomes an empty string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")  # plain notation
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def parse_decimal(value: Any, fmt: ValueFormat = PLAIN) -> Decimal | None:
    """A JSON number, or text in the format's exact notation, that fits storage precision."""
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, str) and fmt.number_pattern.fullmatch(text := value.strip()):
        if fmt.thousands_separator:
            text = text.replace(fmt.thousands_separator, "")
        number = Decimal(text.replace(fmt.decimal_separator, "."))
    else:
        return None
    return number if fits_storage(number) else None


def parse_date(value: Any, fmt: ValueFormat = PLAIN) -> date | None:
    """A date written exactly in the format's notation (zero-padded, nothing extra)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = datetime.strptime(text, fmt.date_format).date()
    except ValueError:
        return None
    return parsed if parsed.strftime(fmt.date_format) == text else None


def parse_text(value: Any, fmt: ValueFormat = PLAIN) -> str | None:
    """Text with surrounding whitespace removed; None when empty."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = to_raw(value).strip()
    return text or None


def parse_uom(value: Any, fmt: ValueFormat = PLAIN) -> Unit | None:
    """A vendor unit: an exact shared alias (M7) or a unit word the format declares."""
    text = parse_text(value)
    if text is None:
        return None
    return fmt.units.get(text.upper()) or unit_from_alias(text)


def parse_currency(value: Any, fmt: ValueFormat = PLAIN) -> str | None:
    """A three-letter upper-case ISO 4217 code."""
    text = parse_text(value)
    return text if text and _CURRENCY.fullmatch(text) else None


def parse_document_type(value: Any, fmt: ValueFormat = PLAIN) -> DocumentType | None:
    """INVOICE, MEMO or CREDIT_MEMO."""
    text = parse_text(value)
    return DocumentType(text.upper()) if text and text.upper() in DocumentType.__members__ else None


# How each canonical field is parsed. Everything not listed is plain text.
FIELD_PARSERS: dict[str, Callable[[Any, ValueFormat], Any]] = {
    "document_type": parse_document_type,
    "invoice_date": parse_date,
    "currency": parse_currency,
    "subtotal": parse_decimal,
    "tax": parse_decimal,
    "total": parse_decimal,
    "quantity": parse_decimal,
    "unit_price": parse_decimal,
    "amount": parse_decimal,
    "qty_backordered": parse_decimal,
    "uom": parse_uom,
}


def read(field: str, value: Any, fmt: ValueFormat = PLAIN) -> RawValue[Any]:
    """Turn a source value into a RawValue for the canonical `field`, in the file's format."""
    if value is MISSING:
        return ABSENT
    parser = FIELD_PARSERS.get(field, parse_text)
    return RawValue(to_raw(value), parser(value, fmt) if value is not None else None)
