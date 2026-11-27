"""Declarative file formats with the code JSON and CSV share.

A layout maps canonical fields to where they live in the file: a dotted path in JSON
or a column name in CSV. Both kinds detect a format with one rule:

    required fields  ⊆  fields found in the file  ⊆  known fields (mapped + ignored)

so any renamed, added or missing field means "format not recognized". There is no
fuzzy matching (R10): a changed file produces an alert instead of a guess.

A layout instance is itself the detector passed to @register: it is callable and also
offers `explain()`, which describes how a file differs from the format.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from .types import ABSENT, DocumentType, LineType, ParsedInvoice, ParsedLine, RawValue, SourceFile
from .values import MISSING, PLAIN, ValueFormat, read

# M5: unambiguous English codes of non-merchandise rows.
CHARGE_CODES = frozenset({"FREIGHT", "SHIPPING", "INSURANCE", "SHIPPING_INSURANCE", "INSURED_SHIPPING"})


class FormatError(Exception):
    """The file was recognized as a format but its content contradicts that format."""


def classify(item_code: RawValue[str], quantity: RawValue[Any], fmt: ValueFormat = PLAIN) -> LineType:
    """M5: a charge code (shared or the format's own) is a charge; no code and no quantity is a summary row."""
    code = (item_code.value or "").upper()
    if code in CHARGE_CODES or code in fmt.charge_codes:
        return LineType.CHARGE
    if item_code.value is None and (quantity.raw is None or not quantity.raw.strip()):
        return LineType.SUMMARY
    return LineType.PRODUCT


def build_line(
    line_no: int,
    values: Mapping[str, RawValue[Any]],
    serials: tuple[str, ...] = (),
    line_type: LineType | None = None,
    fmt: ValueFormat = PLAIN,
) -> ParsedLine:
    """Build a ParsedLine from canonical values; the type is classified unless given."""
    if line_type is None:
        line_type = classify(values.get("item_code", ABSENT), values.get("quantity", ABSENT), fmt)
    return ParsedLine(line_no=line_no, line_type=line_type, serials=serials, **values)


def diff_text(missing: set[str], unexpected: set[str]) -> str:
    """Human-readable difference between a file and a format, for alerts."""
    return f"missing={sorted(missing)} unexpected={sorted(unexpected)}"


# --- JSON -----------------------------------------------------------------------


def json_paths(data: Any, prefix: str = "") -> set[str]:
    """Every key path in a JSON document: `vendor.name`, `lines[].uom`, ..."""
    paths: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}{key}"
            paths.add(path)
            if isinstance(value, dict):
                paths |= json_paths(value, f"{path}.")
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        paths |= json_paths(item, f"{path}[].")
    return paths


def get_path(data: Any, path: str) -> Any:
    """The value at a dotted path, or MISSING."""
    for key in path.split("."):
        if not isinstance(data, dict) or key not in data:
            return MISSING
        data = data[key]
    return data


def read_serials(value: Any) -> tuple[str, ...]:
    """A JSON list of serial numbers; empty strings are not serial numbers."""
    if value is MISSING or value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise FormatError("serial numbers must be a list of strings")
    return tuple(item.strip() for item in value if item.strip())


@dataclass(frozen=True)
class JsonLayout:
    """A JSON format: where each canonical field lives in the document."""

    header: Mapping[str, str]  # canonical field -> dotted path
    line: Mapping[str, str]  # canonical field -> key inside lines[]; "serials" is a list
    charge: Mapping[str, str]  # canonical field -> key inside charges[]
    required: frozenset[str]  # paths without which this is not the format
    ignored: frozenset[str] = frozenset()  # known paths the system does not use
    lines_key: str = "lines"
    charges_key: str = "charges"
    values: ValueFormat = PLAIN  # how numbers and dates written as strings look

    @cached_property
    def known(self) -> frozenset[str]:
        """Every path this format may contain."""
        paths = set(self.ignored) | {self.lines_key, self.charges_key}
        for path in self.header.values():
            parts = path.split(".")
            paths.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
        paths.update(f"{self.lines_key}[].{key}" for key in self.line.values())
        paths.update(f"{self.charges_key}[].{key}" for key in self.charge.values())
        return frozenset(paths)

    def _found(self, src: SourceFile) -> set[str] | None:
        """Paths present in the file, or None if it is not a JSON object."""
        return json_paths(src.json) if isinstance(src.json, dict) else None

    def __call__(self, src: SourceFile) -> bool:
        """Detector: the file contains every required path and nothing unknown."""
        found = self._found(src)
        return found is not None and self.required <= found <= self.known

    def explain(self, src: SourceFile) -> str | None:
        """How the file differs from this format; None if the file is not JSON."""
        found = self._found(src)
        return None if found is None else diff_text(self.required - found, found - self.known)

    def parse(self, src: SourceFile) -> ParsedInvoice:
        """Read the document into canonical form."""
        data = src.json
        fmt = self.values
        header = {name: read(name, get_path(data, path), fmt) for name, path in self.header.items()}
        lines: list[ParsedLine] = []
        for item in self._objects(data, self.lines_key):
            values = {
                name: read(name, item.get(key, MISSING), fmt) for name, key in self.line.items() if name != "serials"
            }
            serials = read_serials(item.get(self.line["serials"], MISSING)) if "serials" in self.line else ()
            lines.append(build_line(len(lines) + 1, values, serials, fmt=fmt))
        for item in self._objects(data, self.charges_key):
            values = {name: read(name, item.get(key, MISSING), fmt) for name, key in self.charge.items()}
            lines.append(build_line(len(lines) + 1, values, line_type=LineType.CHARGE))
        return ParsedInvoice(lines=tuple(lines), **header)

    @staticmethod
    def _objects(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
        """The list of objects under `key` (absent or null means none)."""
        items = data.get(key)
        if items is None:
            return []
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise FormatError(f"'{key}' must be a list of objects")
        return items


# --- CSV ------------------------------------------------------------------------


@dataclass(frozen=True)
class CsvLayout:
    """A CSV format: delimiter and the column of each canonical field.

    Header fields repeat on every row and must agree across rows. A CSV has no
    document type column, so the format declares it. A format may also carry the
    invoice total on a labelled row (Lucentara's TOTALE) instead of a column.
    """

    delimiter: str
    header: Mapping[str, str]  # canonical field -> column, same value on every row
    line: Mapping[str, str]  # canonical field -> column
    header_charges: Mapping[str, str] = field(default_factory=dict)  # charge code -> column
    ignored: frozenset[str] = frozenset()  # known columns the system does not use
    document_type: DocumentType = DocumentType.INVOICE
    values: ValueFormat = PLAIN  # how this format writes numbers and dates
    total_row: tuple[str, str] | None = None  # (canonical line field, exact text) of the total row

    @cached_property
    def known(self) -> frozenset[str]:
        """Exactly the columns this format has (order does not matter)."""
        return frozenset({*self.header.values(), *self.line.values(), *self.header_charges.values(), *self.ignored})

    def __call__(self, src: SourceFile) -> bool:
        """Detector: the header row has exactly this format's columns."""
        return src.json is None and src.csv_columns(self.delimiter) == self.known

    def explain(self, src: SourceFile) -> str | None:
        """How the file's columns differ from this format; None if the file is JSON."""
        if src.json is not None:
            return None
        found = src.csv_columns(self.delimiter)
        if found is None:
            return "header row missing or has repeated column names"
        return diff_text(set(self.known - found), set(found - self.known))

    def parse(self, src: SourceFile) -> ParsedInvoice:
        """Read the rows into canonical form."""
        rows = src.csv_rows(self.delimiter) or []
        columns, body = rows[0], rows[1:]
        if not body:
            raise FormatError("the file has a header but no rows")
        records = []
        for row_no, row in enumerate(body, start=2):
            if len(row) != len(columns):
                raise FormatError(f"row {row_no} has {len(row)} cells but the header has {len(columns)}")
            records.append(dict(zip(columns, row, strict=True)))

        shared = {
            col: self._same_in_every_row(records, col) for col in {*self.header.values(), *self.header_charges.values()}
        }
        fmt = self.values
        header: dict[str, RawValue[Any]] = {name: read(name, shared[col], fmt) for name, col in self.header.items()}
        # Declared by the format, not read from a column.
        header["document_type"] = RawValue(self.document_type.value, self.document_type)
        total = self._take_total_row(records)
        if total is not None:
            header["total"] = read("total", total, fmt)

        lines = [
            build_line(i, {name: read(name, record[col], fmt) for name, col in self.line.items()}, fmt=fmt)
            for i, record in enumerate(records, start=1)
        ]
        for code, col in self.header_charges.items():
            if shared[col].strip():  # an empty charge column means no charge
                values = {"item_code": RawValue(col, code), "amount": read("amount", shared[col], fmt)}
                lines.append(build_line(len(lines) + 1, values, line_type=LineType.CHARGE))
        return ParsedInvoice(lines=tuple(lines), **header)

    def _take_total_row(self, records: list[dict[str, str]]) -> str | None:
        """Remove the format's total row from `records` and return its amount text."""
        if self.total_row is None:
            return None
        field_name, label = self.total_row
        column = self.line[field_name]
        rows = [record for record in records if record[column].strip() == label]
        if len(rows) > 1:
            raise FormatError(f"more than one {label!r} row")
        if not rows:
            return None
        records.remove(rows[0])
        return rows[0][self.line["amount"]]

    @staticmethod
    def _same_in_every_row(records: list[dict[str, str]], column: str) -> str:
        """The single value of a header column; blank cells are ignored, conflicts are errors."""
        values = {record[column].strip() for record in records if record[column].strip()}
        if len(values) > 1:
            raise FormatError(f"column {column!r} has different values in different rows")
        return values.pop() if values else ""
