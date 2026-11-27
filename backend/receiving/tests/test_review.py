"""Review (R5): a person corrects the interpretation, the system validates again, then approve."""

from decimal import Decimal

import pytest

from receiving.models import AuditEvent, Invoice, POLine, Product, PurchaseOrder, SerialUnit, Vendor
from receiving.services import (
    CannotApprove,
    InvalidTransition,
    NeedsConfirmation,
    ServiceError,
    approve,
    edit_invoice,
    edit_line,
)

from .conftest import sample_bytes

Status = Invoice.Status


def codes(invoice: Invoice) -> list[str]:
    """Open issue codes that need a person (info excluded), sorted."""
    return sorted(invoice.issues.exclude(kind="info").values_list("code", flat=True))


def line(invoice: Invoice, line_no: int):
    """An invoice line by its position."""
    return invoice.lines.get(line_no=line_no)


def stock(*skus: str) -> dict[str, Decimal]:
    """Current on-hand of some SKUs."""
    return {p.sku: p.on_hand for p in Product.objects.filter(sku__in=skus)}


def test_choosing_the_skus_of_inv_06_lets_it_be_received(ingest):
    """Unmapped vendor codes are a person's choice; once made, the lines match PO-2026-038 exactly."""
    invoice = ingest("inv_06.csv")
    assert codes(invoice) == ["SKU_UNMAPPED", "SKU_UNMAPPED"]
    before = stock("MTL-6003", "MTL-6004", "FND-4004")

    edit_line(invoice.pk, line(invoice, 2).pk, "staff", {"product": Product.objects.get(pk="MTL-6004")})
    edit_line(invoice.pk, line(invoice, 3).pk, "staff", {"product": Product.objects.get(pk="FND-4004")})
    invoice.refresh_from_db()
    assert codes(invoice) == []
    assert invoice.status == Status.NEEDS_REVIEW  # a person still decides
    assert invoice.status_notes.startswith("Ready for approval")
    assert line(invoice, 2).quantity == Decimal("300")  # 300 G converted to the SKU's unit, gram

    approve(invoice.pk, "staff")
    after = stock("MTL-6003", "MTL-6004", "FND-4004")
    assert {sku: after[sku] - before[sku] for sku in after} == {
        "MTL-6003": Decimal("500"),
        "MTL-6004": Decimal("300"),
        "FND-4004": Decimal("500"),
    }
    assert PurchaseOrder.objects.get(pk="PO-2026-038").status == "received"
    edits = AuditEvent.objects.filter(invoice=invoice, action="edited").order_by("id")
    assert [e.payload["changed"]["product"] for e in edits] == [
        {"from": None, "to": "MTL-6004"},
        {"from": None, "to": "FND-4004"},
    ]
    assert line(invoice, 2).edited_fields == ["product"]


def test_entering_the_missing_certificate_of_inv_09(ingest):
    """M8: three diamonds need three certificate numbers; the person types the third from the paper."""
    invoice = ingest("inv_09.json")
    assert codes(invoice) == ["SERIAL_COUNT_MISMATCH"]
    with pytest.raises(CannotApprove):
        approve(invoice.pk, "staff")
    first = line(invoice, 1)
    edit_line(invoice.pk, first.pk, "staff", {"serials": [*first.serials, "RPT-7391190099"]})
    approve(invoice.pk, "staff")
    assert SerialUnit.objects.filter(product_id="DIA-5001").count() == 3


def test_a_certificate_already_in_stock_is_refused(ingest):
    """A certificate number entered during review that was already received blocks approval."""
    received = ingest("inv_09.json")
    first = line(received, 1)
    edit_line(received.pk, first.pk, "staff", {"serials": [*first.serials, "RPT-7391190099"]})
    approve(received.pk, "staff")

    again = ingest("inv_09.json", sample_bytes("inv_09.json").replace(b"BDC-INV-55204", b"BDC-INV-55299"))
    edit_line(again.pk, line(again, 1).pk, "staff", {"serials": ["A-1", "A-2", "RPT-7391190099"]})
    again.refresh_from_db()
    assert "SERIAL_DUPLICATE" in codes(again)


def test_entering_quantities_for_an_unknown_unit_in_inv_07(ingest):
    """PR is not a unit the system knows: the person enters the quantity in each; the notes change nothing."""
    invoice = ingest("inv_07.json")
    assert codes(invoice) == ["NOT_ON_PO", "UOM_UNKNOWN", "UOM_UNKNOWN"]
    edit_line(invoice.pk, line(invoice, 1).pk, "staff", {"quantity": Decimal("3")})
    edit_line(invoice.pk, line(invoice, 2).pk, "staff", {"quantity": Decimal("2")})
    invoice.refresh_from_db()
    assert codes(invoice) == ["NOT_ON_PO", "OVER_RECEIPT"]  # 3 pairs against 2 ordered
    with pytest.raises(NeedsConfirmation):
        approve(invoice.pk, "staff")
    approve(invoice.pk, "staff", accept_discrepancies=True)
    invoice.refresh_from_db()
    assert invoice.status == Status.RECEIVED  # never the status the vendor's notes asked for
    assert POLine.objects.get(purchase_order_id="PO-2026-043", product_id="EAR-3002").qty_received == Decimal("3")


def test_changing_the_po_rederives_the_lines_and_revert_restores_them(ingest):
    """A header edit re-runs the interpretation: vendor and PO lines follow the chosen PO."""
    invoice = ingest("inv_06.csv")
    edit_invoice(invoice.pk, "staff", {"purchase_order": PurchaseOrder.objects.get(pk="PO-2026-041")})
    invoice.refresh_from_db()
    assert invoice.vendor_id == "V05"  # the vendor comes from the PO (M1)
    assert line(invoice, 1).product is None  # Halvorsen codes are not in Lucentara's map
    assert invoice.edited_fields == ["purchase_order"]

    edit_invoice(invoice.pk, "staff", {}, revert=["purchase_order"])
    invoice.refresh_from_db()
    assert (invoice.purchase_order_id, invoice.vendor_id, invoice.edited_fields) == ("PO-2026-038", "V06", [])
    assert line(invoice, 1).product_id == "MTL-6003"
    assert line(invoice, 1).po_line is not None


def test_an_edit_cannot_turn_an_invoice_into_a_second_live_copy(ingest):
    """Changing vendor and number to those of a live invoice is refused, and nothing is changed."""
    ingest("inv_01.json")
    invoice = ingest("inv_02.json")
    with pytest.raises(ServiceError, match="already has vendor V01"):
        edit_invoice(invoice.pk, "staff", {"vendor": Vendor.objects.get(pk="V01"), "invoice_number": "10482"})
    invoice.refresh_from_db()
    assert (invoice.vendor_id, invoice.invoice_number, invoice.edited_fields) == ("V04", "MBS-2026-0417", [])


def test_marking_a_line_as_a_charge_drops_its_product_edits(ingest):
    """A charge has no product: earlier SKU choices on the line no longer apply."""
    invoice = ingest("inv_06.csv")
    target = line(invoice, 2)
    edit_line(invoice.pk, target.pk, "staff", {"product": Product.objects.get(pk="MTL-6004")})
    edit_line(invoice.pk, target.pk, "staff", {"line_type": "charge"})
    target.refresh_from_db()
    assert (target.line_type, target.product, target.quantity, target.edited_fields) == (
        "charge",
        None,
        None,
        ["line_type"],
    )


def test_edits_are_refused_once_a_decision_is_made_or_when_nothing_was_read(ingest):
    """Received, rejected and unreadable invoices cannot be edited; unknown fields are refused."""
    received = ingest("inv_01.json")
    with pytest.raises(InvalidTransition):
        edit_invoice(received.pk, "staff", {"invoice_number": "X"})
    unreadable = ingest("inv_06.csv", sample_bytes("inv_06.csv").replace(b",UM,", b",UOM,"))
    with pytest.raises(InvalidTransition, match="nothing to correct"):
        edit_invoice(unreadable.pk, "staff", {"invoice_number": "X"})
    invoice = ingest("inv_02.json")
    with pytest.raises(ServiceError, match="cannot be edited: status"):
        edit_invoice(invoice.pk, "staff", {"status": "received"})


def test_reverting_a_line_type_restores_the_parsers_type(ingest):
    """Revert hands the line type back to what the format's parser read, not the edited value."""
    invoice = ingest("inv_06.csv")
    target = line(invoice, 1)
    edit_line(invoice.pk, target.pk, "staff", {"line_type": "charge"})
    edit_line(invoice.pk, target.pk, "staff", {}, revert=["line_type"])
    target.refresh_from_db()
    assert (target.line_type, target.edited_fields, target.product_id) == ("product", [], "MTL-6003")


def test_a_refused_approval_saves_what_the_new_validation_found(ingest):
    """Another invoice received the same PO lines meanwhile: the new discrepancies are stored and shown."""
    first = ingest("inv_06.csv")
    second = ingest("inv_06.csv", sample_bytes("inv_06.csv").replace(b"HS-88213", b"HS-88214"))
    for invoice in (first, second):
        edit_line(invoice.pk, line(invoice, 2).pk, "staff", {"product": Product.objects.get(pk="MTL-6004")})
        edit_line(invoice.pk, line(invoice, 3).pk, "staff", {"product": Product.objects.get(pk="FND-4004")})
    approve(first.pk, "staff")
    with pytest.raises(NeedsConfirmation):
        approve(second.pk, "staff")
    second.refresh_from_db()
    assert codes(second) == ["OVER_RECEIPT", "OVER_RECEIPT", "OVER_RECEIPT"]
    assert second.status_notes.startswith("Needs review.") and "exceeds" in second.status_notes
