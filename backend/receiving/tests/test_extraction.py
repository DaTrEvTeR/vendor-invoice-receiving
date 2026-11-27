"""Extraction: the parser registry, strict value parsing and format-change alerts (R4, R9, R10)."""

import json
import logging
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured

from receiving.extraction import DECODE_FAILED, NO_PARSER, PARSER_FAILED, ExtractionError, extract, registry
from receiving.extraction.layouts import classify
from receiving.extraction.parsers.invoice_json import INVOICE_JSON_V1
from receiving.extraction.types import DocumentType, LineType, RawValue, SourceFile
from receiving.extraction.values import PLAIN, ValueFormat, parse_date, parse_decimal, parse_uom
from receiving.units import Unit

from .conftest import sample_bytes

SAMPLES = [f"inv_{n:02d}.{'csv' if n in (3, 6, 12) else 'json'}" for n in range(1, 13)]
US = ValueFormat(decimal_separator=".", thousands_separator=",", date_format="%m/%d/%Y")
ITALIAN = ValueFormat(decimal_separator=",", thousands_separator=".", date_format="%d/%m/%Y")
CSV_PARSERS = {
    "inv_03.csv": "v01_thistlewood_csv",
    "inv_06.csv": "v06_halvorsen_csv",
    "inv_12.csv": "v05_lucentara_csv",
}


def source(name: str, data: bytes | None = None) -> SourceFile:
    """A SourceFile for a sample, optionally with replaced content."""
    return SourceFile.from_bytes(name, sample_bytes(name) if data is None else data)


@pytest.mark.parametrize("name", SAMPLES)
def test_every_sample_is_read_by_its_parser(name):
    """Each of the 12 files is recognized by exactly the expected parser."""
    assert extract(source(name)).parser_key == CSV_PARSERS.get(name, "invoice_json_v1")


def test_json_numbers_are_decimals_never_floats():
    """Money never passes through float."""
    line = extract(source("inv_10.json")).lines[0]
    assert line.amount.value == Decimal("1866.25") and isinstance(line.amount.value, Decimal)
    assert line.unit_price.value == Decimal("74.65")
    assert line.uom.value is Unit.DWT


def test_thistlewood_csv_reads_us_notation_and_freight_column():
    """inv_03: '2,085.00' and month-first '11/03/2026' are this format's notation; freight is one charge."""
    parsed = extract(source("inv_03.csv"))
    assert [line.line_type for line in parsed.lines] == [LineType.PRODUCT] * 3 + [LineType.CHARGE]
    freight = parsed.lines[3]
    assert (freight.item_code.value, freight.amount.value) == ("FREIGHT", Decimal("35.00"))
    assert (parsed.total.raw, parsed.total.value) == ("2,085.00", Decimal("2085.00"))
    assert (parsed.invoice_date.raw, parsed.invoice_date.value) == ("11/03/2026", date(2026, 11, 3))
    assert parsed.lines[0].uom.raw is None  # the format has no unit column: a person decides
    assert parsed.document_type.value is DocumentType.INVOICE  # declared by the format


def test_halvorsen_csv_freight_row_is_a_charge():
    """inv_06: a FREIGHT row is a charge, G and EA are exact unit aliases."""
    parsed = extract(source("inv_06.csv"))
    assert [line.line_type for line in parsed.lines] == [LineType.PRODUCT] * 3 + [LineType.CHARGE]
    assert [line.uom.value for line in parsed.lines[:3]] == [Unit.GRAM, Unit.GRAM, Unit.EACH]


def test_lucentara_csv_reads_italian_notation_and_the_totale_row():
    """inv_12: decimal commas and day-first dates are this format's notation; TOTALE is the invoice total."""
    parsed = extract(source("inv_12.csv"))
    assert parsed.currency.value == "EUR"
    assert (parsed.invoice_date.raw, parsed.invoice_date.value) == ("04/05/2026", date(2026, 5, 4))
    assert (parsed.total.raw, parsed.total.value) == ("3.422,00", Decimal("3422.00"))
    assert len(parsed.lines) == 4  # the TOTALE row is the total, not a line
    assert [line.amount.value for line in parsed.lines] == [
        Decimal("1125.00"),
        Decimal("1484.00"),
        Decimal("768.00"),
        Decimal("45.00"),
    ]
    assert [line.unit_price.value for line in parsed.lines] == [
        Decimal("112.50"),
        Decimal("742.00"),
        Decimal("128.00"),
        Decimal("45.00"),
    ]
    assert (parsed.lines[0].uom.raw, parsed.lines[0].uom.value) == ("PZ", Unit.EACH)  # the format's unit word
    assert parsed.lines[3].line_type is LineType.CHARGE  # SPED is the format's code for shipping


def test_a_formats_own_words_mean_nothing_in_another_format():
    """PZ and SPED are Lucentara's vocabulary only: in a JSON invoice they stay unknown."""
    data = sample_bytes("inv_01.json").replace(b'"EA"', b'"PZ"', 1)
    parsed = extract(source("inv_01.json", data))
    assert (parsed.lines[0].uom.raw, parsed.lines[0].uom.value) == ("PZ", None)
    assert parse_uom("PZ") is None and classify(RawValue("SPED", "SPED"), RawValue("1", 1)) is LineType.PRODUCT


def test_a_value_in_another_notation_is_not_guessed():
    """A US-style number inside the Italian format does not match its notation and stays unparsed."""
    data = sample_bytes("inv_12.csv").replace(b";768,00\n", b";768.00\n")
    line = extract(source("inv_12.csv", data)).lines[2]
    assert (line.amount.raw, line.amount.value) == ("768.00", None)


@pytest.mark.parametrize(
    "text, fmt, expected",
    [
        ("123", PLAIN, Decimal("123")),
        ("-92.50", PLAIN, Decimal("-92.50")),
        (" 10 ", PLAIN, Decimal("10")),
        ("112,50", PLAIN, None),
        ("2,085.00", PLAIN, None),
        ("1e3", PLAIN, None),
        ("1.0000001", PLAIN, None),  # would be rounded by storage
        ("", PLAIN, None),
        ("2,085.00", US, Decimal("2085.00")),
        ("2085.00", US, Decimal("2085.00")),
        ("1,125,000.5", US, Decimal("1125000.5")),
        ("20,85.00", US, None),  # misplaced group separator
        ("112,50", US, None),
        ("1.125,00", ITALIAN, Decimal("1125.00")),
        ("112,50", ITALIAN, Decimal("112.50")),
        ("10", ITALIAN, Decimal("10")),
        ("1,125.00", ITALIAN, None),
        ("1.12", ITALIAN, None),
    ],
)
def test_numbers_must_match_the_declared_notation_exactly(text, fmt, expected):
    """R4: a number is read only in the notation its format declares."""
    assert parse_decimal(text, fmt) == expected


@pytest.mark.parametrize(
    "text, fmt, expected",
    [
        ("2026-11-03", PLAIN, date(2026, 11, 3)),
        ("04/05/2026", PLAIN, None),
        ("2026-13-01", PLAIN, None),
        ("11/03/2026", US, date(2026, 11, 3)),
        ("04/05/2026", ITALIAN, date(2026, 5, 4)),
        ("4/5/2026", ITALIAN, None),  # not zero-padded: not this format
        ("31/02/2026", ITALIAN, None),
    ],
)
def test_dates_must_match_the_declared_notation_exactly(text, fmt, expected):
    """R4: a date is read only in the notation its format declares."""
    assert parse_date(text, fmt) == expected


def error_messages(caplog) -> str:
    """Text of every ERROR record logged by extraction."""
    return " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)


def test_renamed_csv_column_raises_an_alert_with_the_difference(caplog):
    """A vendor renames UM to UOM: no parser matches, the log says exactly what changed."""
    data = sample_bytes("inv_06.csv").replace(b",UM,", b",UOM,")
    with pytest.raises(ExtractionError) as error:
        extract(source("inv_06.csv", data))
    assert error.value.code == NO_PARSER
    assert "v06_halvorsen_csv: missing=['UM'] unexpected=['UOM']" in error_messages(caplog)


def test_new_json_field_is_not_silently_ignored(caplog):
    """An unknown key could carry meaning (a discount, say): it is an alert, not a guess."""
    document = json.loads(sample_bytes("inv_01.json"))
    document["discount"] = 10
    with pytest.raises(ExtractionError):
        extract(source("inv_01.json", json.dumps(document).encode()))
    assert "invoice_json_v1: missing=[] unexpected=['discount']" in error_messages(caplog)


def test_csv_rows_that_disagree_on_header_fields_fail_loudly(caplog):
    """Two invoice numbers in one file: the parser refuses instead of picking one."""
    data = sample_bytes("inv_06.csv").replace(
        b"HS-88213,2026-11-12,PO-2026-038,HS-JR5-SS", b"HS-88214,2026-11-12,PO-2026-038,HS-JR5-SS"
    )
    with pytest.raises(ExtractionError) as error:
        extract(source("inv_06.csv", data))
    assert error.value.code == PARSER_FAILED
    assert PARSER_FAILED in error_messages(caplog)


def test_bytes_that_are_not_utf8_are_not_parsed(caplog):
    """A Latin-1 file would decode into wrong text; it goes to a person instead."""
    data = sample_bytes("inv_06.csv").replace(b"Sterling", "Sterlíng".encode("latin-1"))
    with pytest.raises(ExtractionError) as error:
        extract(source("inv_06.csv", data))
    assert error.value.code == DECODE_FAILED


def test_registry_refuses_duplicate_keys_and_tries_higher_priority_first(monkeypatch):
    """Keys are unique; a vendor-specific parser with a higher priority beats the generic one."""
    monkeypatch.setattr(registry, "_PARSERS", dict(registry._PARSERS))
    with pytest.raises(ImproperlyConfigured):
        registry.register("invoice_json_v1", detect=lambda src: False)(lambda src: None)

    @registry.register("vendor_specific_json", detect=INVOICE_JSON_V1, priority=20)
    def parse_specific(src):
        """Same layout, registered with a higher priority."""
        return INVOICE_JSON_V1.parse(src)

    assert extract(source("inv_01.json")).parser_key == "vendor_specific_json"
