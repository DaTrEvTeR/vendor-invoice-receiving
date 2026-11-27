"""Data structures of the extraction layer. Pure Python, no database access."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from enum import StrEnum
from functools import cached_property
from typing import Any


class DocumentType(StrEnum):
    """Kinds of vendor documents the system knows."""

    INVOICE = "INVOICE"
    MEMO = "MEMO"  # consignment: the vendor keeps title to the goods
    CREDIT_MEMO = "CREDIT_MEMO"  # credit for returned goods


class LineType(StrEnum):
    """What an invoice row is."""

    PRODUCT = "product"  # merchandise: the only kind that can reach stock
    CHARGE = "charge"  # freight, insurance
    SUMMARY = "summary"  # no item code and no quantity: shown, never received


@dataclass(frozen=True, slots=True)
class RawValue[T]:
    """One field as it appeared in the file (`raw`) and as strictly parsed (`value`).

    raw is None: the field is not part of this file format.
    raw is "" (or blank): the field exists but is empty.
    value is None while raw has text: the text is ambiguous or malformed.
    """

    raw: str | None = None
    value: T | None = None

    @property
    def is_blank(self) -> bool:
        """The field exists in the format but holds no text."""
        return self.raw is not None and not self.raw.strip()

    @property
    def unparsed(self) -> bool:
        """The field has text that could not be read unambiguously."""
        return self.raw is not None and bool(self.raw.strip()) and self.value is None


ABSENT: RawValue[Any] = RawValue()


@dataclass(frozen=True, slots=True)
class ParsedLine:
    """One row of the invoice in canonical form. `line_no` is its position (1-based)."""

    line_no: int
    line_type: LineType
    vendor_line_no: RawValue[str] = ABSENT
    item_code: RawValue[str] = ABSENT
    description: RawValue[str] = ABSENT
    quantity: RawValue[Decimal] = ABSENT  # in the vendor's unit
    uom: RawValue[str] = ABSENT  # value is a catalog unit, or None
    unit_price: RawValue[Decimal] = ABSENT
    amount: RawValue[Decimal] = ABSENT
    qty_backordered: RawValue[Decimal] = ABSENT
    serials: tuple[str, ...] = ()

    def raw_dict(self) -> dict[str, Any]:
        """Canonical field -> text as in the file, for InvoiceLine.raw."""
        result: dict[str, Any] = _raw_fields(self)
        if self.serials:
            result["serials"] = list(self.serials)
        return result

    def parsed_dict(self) -> dict[str, Any]:
        """Canonical field -> value as the format's parser read it, plus the line type it assigned."""
        result: dict[str, Any] = {"line_type": self.line_type.value, **_parsed_fields(self)}
        if self.serials:
            result["serials"] = list(self.serials)
        return result

    def unparsed_count(self) -> int:
        """Number of fields whose text could not be read."""
        return _unparsed(self)


@dataclass(frozen=True, slots=True)
class ParsedInvoice:
    """The whole document in canonical form: the contract between Extract and Transform."""

    parser_key: str = ""
    document_type: RawValue[str] = ABSENT
    vendor_name: RawValue[str] = ABSENT
    invoice_number: RawValue[str] = ABSENT
    invoice_date: RawValue[date] = ABSENT
    currency: RawValue[str] = ABSENT
    po_reference: RawValue[str] = ABSENT
    subtotal: RawValue[Decimal] = ABSENT
    tax: RawValue[Decimal] = ABSENT
    total: RawValue[Decimal] = ABSENT
    notes: RawValue[str] = ABSENT
    references_invoice: RawValue[str] = ABSENT
    lines: tuple[ParsedLine, ...] = ()

    def raw_header(self) -> dict[str, str]:
        """Canonical header field -> text as in the file, for Invoice.raw_header."""
        return _raw_fields(self)

    def parsed_header(self) -> dict[str, Any]:
        """Canonical header field -> value as the format's parser read it, for Invoice.parsed_header."""
        return _parsed_fields(self)

    def unparsed_count(self) -> int:
        """Number of header and line fields whose text could not be read."""
        return _unparsed(self) + sum(line.unparsed_count() for line in self.lines)


def _raw_values(obj: Any) -> dict[str, RawValue[Any]]:
    """The RawValue fields of a parsed dataclass, by name."""
    return {f.name: getattr(obj, f.name) for f in fields(obj) if isinstance(getattr(obj, f.name), RawValue)}


def _raw_fields(obj: Any) -> dict[str, str]:
    """Raw text of every field that exists in the file format."""
    return {name: rv.raw for name, rv in _raw_values(obj).items() if rv.raw is not None}


def to_json_value(value: Any) -> Any:
    """A parsed value as JSON: decimals as plain text (exact), dates as ISO, enums as their value."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


def _parsed_fields(obj: Any) -> dict[str, Any]:
    """Parsed value (None when unreadable) of every field that exists in the file format."""
    return {name: to_json_value(rv.value) for name, rv in _raw_values(obj).items() if rv.raw is not None}


def _unparsed(obj: Any) -> int:
    """How many fields of `obj` have unreadable text."""
    return sum(rv.unparsed for rv in _raw_values(obj).values())


@dataclass(frozen=True)
class SourceFile:
    """An uploaded file: its name, decoded text and the SHA-256 of the original bytes."""

    name: str
    text: str
    sha256: str
    decoded: bool  # False when the bytes were not valid UTF-8

    @classmethod
    def from_bytes(cls, name: str, data: bytes) -> SourceFile:
        """Decode as UTF-8 (a BOM is dropped). Invalid bytes are kept visible as U+FFFD."""
        sha256 = hashlib.sha256(data).hexdigest()
        try:
            return cls(name, data.decode("utf-8-sig"), sha256, True)
        except UnicodeDecodeError:
            return cls(name, data.decode("utf-8", errors="replace"), sha256, False)

    @cached_property
    def json(self) -> Any | None:
        """The parsed JSON document with every number as Decimal, or None if not JSON."""
        try:
            return json.loads(self.text, parse_float=Decimal, parse_int=Decimal)
        except ValueError:
            return None

    def csv_rows(self, delimiter: str) -> list[list[str]] | None:
        """Non-blank CSV rows (header first), or None if the text is not valid CSV."""
        try:
            rows = list(csv.reader(io.StringIO(self.text, newline=""), delimiter=delimiter, strict=True))
        except csv.Error:
            return None
        return [row for row in rows if any(cell.strip() for cell in row)]

    def csv_columns(self, delimiter: str) -> frozenset[str] | None:
        """Header names, or None if there is no header or a name repeats."""
        rows = self.csv_rows(delimiter)
        if not rows or len(set(rows[0])) != len(rows[0]):
            return None
        return frozenset(rows[0])
