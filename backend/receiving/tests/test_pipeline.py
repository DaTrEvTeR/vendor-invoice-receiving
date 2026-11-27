"""The whole pipeline: the 12 samples, repeats, approval rules and atomicity."""

import json
import logging
from decimal import Decimal

import pytest
from django.conf import settings
from django.db import IntegrityError

from receiving import services
from receiving.models import AuditEvent, Invoice, POLine, Product, PurchaseOrder, SerialUnit, StockMovement
from receiving.outcomes import build_outcomes, submit_samples, to_json
from receiving.seed import load_reference_data, wipe_all
from receiving.services import (
    CannotApprove,
    InvalidTransition,
    NeedsConfirmation,
    UploadRejected,
    approve,
    close,
    ingest_file,
    reject,
)

from .conftest import sample_bytes

Status = Invoice.Status

EXPECTED_STATUSES = {
    "inv_01.json": "received",
    "inv_02.json": "needs_review",
    "inv_03.csv": "duplicate",
    "inv_04.json": "received",
    "inv_12.csv": "received",
    **{
        name: "needs_review"
        for name in [
            "inv_05.json",
            "inv_06.csv",
            "inv_07.json",
            "inv_08.json",
            "inv_09.json",
            "inv_10.json",
            "inv_11.json",
        ]
    },
}


def on_hand(sku: str) -> Decimal:
    """Current stock of a SKU."""
    return Product.objects.get(sku=sku).on_hand


def received(po_number: str, sku: str) -> Decimal:
    """Quantity received so far on a PO line."""
    return POLine.objects.get(purchase_order_id=po_number, product_id=sku).qty_received


def test_golden_run_of_the_twelve_samples(seeded):
    """The brief's scenario: filename order, no human review. This is outcomes.json."""
    submit_samples(settings.DATA_DIR)
    outcomes = build_outcomes()

    assert {i["file"]: i["status"] for i in outcomes["invoices"]} == EXPECTED_STATUSES
    lines = {i["file"]: [tuple(line.values()) for line in i["received_lines"]] for i in outcomes["invoices"]}
    assert lines["inv_01.json"] == [
        ("CHN-2001", "2", "each", "PO-2026-031"),
        ("CHN-2003", "3", "each", "PO-2026-031"),
        ("CHN-2004", "4", "each", "PO-2026-031"),
    ]
    assert lines["inv_04.json"] == [
        ("FND-4003", "120", "each", "PO-2026-036"),
        ("FND-4001", "20", "each", "PO-2026-036"),
        ("FND-4006", "50", "each", "PO-2026-036"),
    ]
    assert lines["inv_12.csv"] == [
        ("EAR-3001", "10", "each", "PO-2026-041"),
        ("RNG-1006", "2", "each", "PO-2026-041"),
        ("EAR-3006", "6", "each", "PO-2026-041"),
    ]
    received_files = ("inv_01.json", "inv_04.json", "inv_12.csv")
    assert all(not received_lines for name, received_lines in lines.items() if name not in received_files)

    inventory = outcomes["inventory"]
    assert len(inventory) == 40
    changed = {
        "CHN-2001": "6",
        "CHN-2003": "8",
        "CHN-2004": "12",
        "FND-4003": "370",
        "FND-4001": "50",
        "FND-4006": "110",
        "EAR-3001": "16",
        "RNG-1006": "3",
        "EAR-3006": "10",
    }
    assert {sku: inventory[sku] for sku in changed} == changed
    assert inventory["MTL-6001"] == "120"  # inv_10 not received
    pos = outcomes["purchase_orders"]
    assert sum(len(lines) for lines in pos.values()) == 21
    assert pos["PO-2026-031"] == {"CHN-2001": "2", "CHN-2003": "3", "CHN-2004": "4"}
    assert pos["PO-2026-036"] == {"FND-4001": "20", "FND-4003": "120", "FND-4006": "50"}
    assert pos["PO-2026-041"] == {"EAR-3001": "10", "EAR-3006": "6", "RNG-1006": "2"}
    assert PurchaseOrder.objects.get(pk="PO-2026-031").status == "received"
    assert PurchaseOrder.objects.get(pk="PO-2026-036").status == "partially_received"
    assert PurchaseOrder.objects.get(pk="PO-2026-041").status == "received"
    touched = ("PO-2026-031", "PO-2026-036", "PO-2026-041")
    assert all(q == "0" for po, lines in pos.items() if po not in touched for q in lines.values())


def test_outcomes_are_deterministic(seeded):
    """Running the scenario again from the same data gives identical bytes."""
    submit_samples(settings.DATA_DIR)
    first = to_json(build_outcomes())
    wipe_all()
    load_reference_data(settings.DATA_DIR)
    submit_samples(settings.DATA_DIR)
    assert to_json(build_outcomes()) == first


def test_ledger_explains_every_stock_level(seeded):
    """After receiving, on_hand still equals the sum of each product's movements."""
    submit_samples(settings.DATA_DIR)
    for product in Product.objects.all():
        assert sum((m.quantity for m in product.movements.all()), Decimal("0")) == product.on_hand


def test_inv_03_is_a_duplicate_but_inv_04_with_the_same_number_is_not(ingest):
    """The duplicate key is vendor plus number, not the number alone (M2)."""
    inv_01 = ingest("inv_01.json")
    inv_03 = ingest("inv_03.csv")
    assert (inv_03.status, inv_03.duplicate_of_id) == (Status.DUPLICATE, inv_01.pk)
    assert ingest("inv_04.json").status == Status.RECEIVED
    assert on_hand("CHN-2001") == Decimal("6")  # received once, not twice


def test_same_bytes_return_the_existing_invoice(seeded):
    """Uploading the same file twice stores it once."""
    first = ingest_file("inv_02.json", sample_bytes("inv_02.json"))
    again = ingest_file("inv_02_copy.json", sample_bytes("inv_02.json"))
    assert (again.created, again.invoice.pk) == (False, first.invoice.pk)
    assert Invoice.objects.count() == 1


def test_a_rejected_file_can_be_submitted_again(ingest):
    """Rejection blocks nothing: the same bytes (after a parser fix, say) are accepted again."""
    first = ingest("inv_02.json")
    reject(first.pk, "staff", "Vendor will send a corrected invoice.")
    again = ingest("inv_02.json")
    assert again.pk != first.pk
    assert again.status == Status.NEEDS_REVIEW


def test_instructions_in_notes_are_ignored(ingest):
    """inv_07 asks importers to record RECEIVED_NGX; notes are data, never commands."""
    invoice = ingest("inv_07.json")
    assert invoice.status == Status.NEEDS_REVIEW
    assert "RECEIVED_NGX" in invoice.notes


def test_discrepancies_need_explicit_acceptance_and_approval_happens_once(ingest):
    """Soft issues block until accepted; a second approve does nothing."""
    invoice = ingest("inv_02.json")
    with pytest.raises(NeedsConfirmation) as error:
        approve(invoice.pk, "staff")
    assert [f.code for f in error.value.findings] == ["TOTALS_MISMATCH"]

    approve(invoice.pk, "staff", accept_discrepancies=True)
    assert on_hand("RNG-1001") == Decimal("10")
    approval = AuditEvent.objects.get(invoice=invoice, action="approved")
    assert approval.payload["accepted_discrepancies"][0]["code"] == "TOTALS_MISMATCH"

    with pytest.raises(InvalidTransition):
        approve(invoice.pk, "staff", accept_discrepancies=True)
    assert on_hand("RNG-1001") == Decimal("10")


def test_hard_issues_block_approval_even_when_accepting(ingest):
    """inv_09: three diamonds, two certificates. Accepting discrepancies does not help."""
    invoice = ingest("inv_09.json")
    with pytest.raises(CannotApprove) as error:
        approve(invoice.pk, "staff", accept_discrepancies=True)
    assert "SERIAL_COUNT_MISMATCH" in [f.code for f in error.value.findings]
    assert on_hand("DIA-5001") == Decimal("2")


def test_memo_can_be_closed_but_never_received(ingest):
    """R6: a consignment memo never reaches on_hand; close is only for memos."""
    memo = ingest("inv_05.json")
    with pytest.raises(CannotApprove):
        approve(memo.pk, "staff", accept_discrepancies=True)
    closed = close(memo.pk, "staff", "Consignment, tracked outside stock.")
    assert closed.status == Status.CLOSED_NO_RECEIPT
    assert on_hand("DIA-5001") == Decimal("2")
    with pytest.raises(InvalidTransition):
        close(ingest("inv_02.json").pk, "staff", "Not a memo.")


def test_approval_revalidates_against_the_current_po(ingest):
    """Between upload and approval another receipt filled the PO line: the over-receipt surfaces."""
    invoice = ingest("inv_02.json")
    POLine.objects.filter(purchase_order_id="PO-2026-034", product_id="RNG-1001").update(qty_received=Decimal("4"))
    with pytest.raises(NeedsConfirmation) as error:
        approve(invoice.pk, "staff")
    assert "OVER_RECEIPT" in [f.code for f in error.value.findings]


def test_a_failure_midway_rolls_back_the_whole_approval(ingest, monkeypatch):
    """A certificate already in stock aborts the approval: no stock, PO or status change."""
    invoice = ingest("inv_08.json")
    opening = StockMovement.objects.filter(product_id="DIA-5003").first()
    SerialUnit.objects.create(product_id="DIA-5003", serial_number="RPT-5528093117", stock_movement=opening)
    monkeypatch.setattr(services, "validate", lambda inv: [])  # skip the check that would catch it first

    with pytest.raises(IntegrityError):
        approve(invoice.pk, "staff")
    invoice.refresh_from_db()
    assert invoice.status == Status.NEEDS_REVIEW
    assert on_hand("DIA-5003") == Decimal("1")
    assert received("PO-2026-029", "DIA-5003") == Decimal("0")
    assert not StockMovement.objects.filter(kind="receipt").exists()


def test_partial_shipment_without_a_backorder_is_a_discrepancy(ingest):
    """M3: a short shipment is information only when the vendor's backorder accounts for it."""
    document = json.loads(sample_bytes("inv_04.json"))
    for line in document["lines"]:
        line.pop("quantity_backordered")
    invoice = ingest("inv_04.json", json.dumps(document).encode())
    assert invoice.status == Status.NEEDS_REVIEW
    assert "SHORT_SHIPMENT" in list(invoice.issues.values_list("code", flat=True))


def test_inv_12_is_received_in_lucentaras_notation_and_vocabulary(ingest):
    """Italian numbers and dates, the TOTALE row, PZ and SPED are all declared by the Lucentara format."""
    invoice = ingest("inv_12.csv")
    assert invoice.status == Status.RECEIVED
    assert (invoice.invoice_date.isoformat(), invoice.total) == ("2026-05-04", Decimal("3422.00"))
    assert [line.line_type for line in invoice.lines.order_by("line_no")] == ["product"] * 3 + ["charge"]
    assert not invoice.issues.exclude(kind="info").exists()
    assert (on_hand("EAR-3001"), received("PO-2026-041", "EAR-3001")) == (Decimal("16"), Decimal("10"))


def test_reject_and_close_reasons_are_optional(ingest):
    """A reason is recorded when given, but not required."""
    assert reject(ingest("inv_02.json").pk, "staff").status == Status.REJECTED
    assert close(ingest("inv_05.json").pk, "staff").status == Status.CLOSED_NO_RECEIPT


def test_an_unrecognized_file_goes_to_a_person_with_an_alert(ingest, caplog):
    """R9: the developer gets an ERROR with the diff, staff get a file they can only reject."""
    data = sample_bytes("inv_06.csv").replace(b",UM,", b",UOM,")
    invoice = ingest("inv_06.csv", data)
    assert invoice.status == Status.NEEDS_REVIEW
    assert list(invoice.issues.values_list("code", "kind")) == [("FORMAT_UNRECOGNIZED", "terminal")]
    assert any(r.levelno == logging.ERROR and "EXTRACTION_NO_PARSER" in r.getMessage() for r in caplog.records)
    with pytest.raises(CannotApprove):
        approve(invoice.pk, "staff", accept_discrepancies=True)
    assert reject(invoice.pk, "staff", "Unknown format, asked the vendor.").status == Status.REJECTED


@pytest.mark.parametrize(
    "name, data",
    [("invoice.pdf", b"%PDF-1.7"), ("empty.csv", b""), ("big.json", b"{" + b" " * 2048 + b"}")],
)
def test_uploads_that_cannot_be_invoices_are_refused(seeded, settings, name, data):
    """Wrong extension, empty or oversized files are not stored at all."""
    settings.MAX_UPLOAD_BYTES = 1024
    with pytest.raises(UploadRejected):
        ingest_file(name, data)
    assert not Invoice.objects.exists()


def test_a_duplicate_file_can_be_processed_once_its_original_is_rejected(ingest):
    """The duplicate's original was rejected: uploading the duplicate's file again processes it."""
    original = ingest("inv_01.json", sample_bytes("inv_01.json").replace(b'"amount": 840.00', b'"amount": 841.00'))
    assert original.status == Status.NEEDS_REVIEW
    assert ingest("inv_03.csv").status == Status.DUPLICATE
    reject(original.pk, "staff")
    again = ingest_file("inv_03.csv", sample_bytes("inv_03.csv"))
    assert again.created  # a new invoice, not the old duplicate row
    assert (again.invoice.status, again.invoice.duplicate_of) == (Status.RECEIVED, None)


def test_a_line_without_a_unit_is_taken_in_the_skus_unit_when_the_po_price_confirms_it(ingest):
    """inv_03 on its own: the Thistlewood CSV has no unit column; each line's PO price confirms 'each'."""
    invoice = ingest("inv_03.csv")
    assert invoice.status == Status.RECEIVED
    assumed = invoice.issues.filter(code="UNIT_ASSUMED")
    assert [(i.kind, i.line.line_no) for i in assumed.order_by("line__line_no")] == [
        ("info", 1),
        ("info", 2),
        ("info", 3),
    ]
    assert "2 taken as each, the unit of CHN-2001, which the PO price confirms" in invoice.status_notes


def test_an_unconfirmed_unit_assumption_needs_a_person(ingest):
    """A blank unit on a line that no PO price confirms is a discrepancy, never silently accepted."""
    invoice = ingest(
        "inv_07.json", sample_bytes("inv_07.json").replace(b'"quantity": 2, "uom": "PR"', b'"quantity": 2, "uom": ""')
    )
    assumed = invoice.issues.get(code="UNIT_ASSUMED")
    assert (assumed.kind, assumed.line.line_no) == ("soft", 2)  # EAR-3005 is not on PO-2026-043
    assert invoice.status == Status.NEEDS_REVIEW


def test_a_converted_quantity_too_large_to_store_goes_to_a_person(ingest):
    """40,000,000 OZT is about 1.24e9 grams: more digits than storage keeps exactly, so nothing is rounded."""
    data = sample_bytes("inv_10.json").replace(b'"quantity": 25, "uom": "DWT"', b'"quantity": 40000000, "uom": "OZT"')
    invoice = ingest("inv_10.json", data)
    assert invoice.status == Status.NEEDS_REVIEW
    assert "VALUE_OUT_OF_RANGE" in invoice.issues.values_list("code", flat=True)
    assert invoice.lines.get(line_no=1).quantity is None
