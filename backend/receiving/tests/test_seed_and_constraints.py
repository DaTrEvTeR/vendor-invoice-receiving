"""Reference data loading and the invariants the database itself enforces."""

import csv
from decimal import Decimal

import pytest
from django.conf import settings
from django.contrib import admin
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import Sum

from receiving.decimals import fits_storage
from receiving.models import (
    Invoice,
    POLine,
    Product,
    PurchaseOrder,
    StockMovement,
    Vendor,
    VendorItem,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    """Load data/ through the management command."""
    call_command("seed_data")


def test_seed_loads_every_reference_row(seeded):
    """Every row of data/ is loaded, with units and currencies as shipped."""
    assert Vendor.objects.count() == 7
    assert Product.objects.count() == 40
    assert VendorItem.objects.count() == 36
    assert PurchaseOrder.objects.count() == 10
    assert POLine.objects.count() == 21
    assert Product.objects.get(sku="MTL-6005").unit == "dwt"
    assert PurchaseOrder.objects.get(po_number="PO-2026-041").currency == "EUR"


def test_seed_keeps_catalog_on_hand_and_explains_it_with_opening_movements(seeded):
    """on_hand matches the catalog and equals the sum of the ledger."""
    with open(settings.DATA_DIR / "catalog.csv", newline="") as f:
        expected = {row["sku"]: Decimal(row["on_hand"]) for row in csv.DictReader(f)}
    for product in Product.objects.all():
        assert product.on_hand == expected[product.sku]
        ledger = product.movements.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
        assert ledger == product.on_hand
    assert set(StockMovement.objects.values_list("kind", flat=True)) == {"opening"}


def test_seed_is_a_noop_when_data_exists_and_reset_reloads(seeded):
    """A second run changes nothing; --reset reloads from data/."""
    Product.objects.filter(sku="RNG-1001").update(name="changed")
    call_command("seed_data")
    assert Product.objects.get(sku="RNG-1001").name == "changed"

    call_command("seed_data", "--reset")
    assert Product.objects.get(sku="RNG-1001").name != "changed"
    assert Product.objects.count() == 40


def test_decimals_round_trip_exactly_through_sqlite(seeded):
    """A 6-decimal quantity comes back from SQLite unchanged."""
    line = POLine.objects.first()
    line.qty_received = Decimal("38.879346")
    line.save()
    line.refresh_from_db()
    assert line.qty_received == Decimal("38.879346")


@pytest.mark.parametrize(
    "value, fits",
    [
        ("38.879346", True),
        ("999999999.999999", True),
        ("-92.5", True),
        ("1.0000001", False),  # 7 decimal places would be rounded
        ("1000000000", False),  # 16 digits with the 6 decimal places
        ("NaN", False),
    ],
)
def test_fits_storage(value, fits):
    """Values that would be rounded by storage are refused."""
    assert fits_storage(Decimal(value)) is fits


def test_on_hand_can_never_go_negative(seeded):
    """The database refuses negative stock."""
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.filter(sku="RNG-1001").update(on_hand=Decimal("-1"))


def test_vendor_item_code_is_unique_per_vendor(seeded):
    """One vendor code maps to one SKU."""
    with pytest.raises(IntegrityError), transaction.atomic():
        VendorItem.objects.create(vendor_id="V01", vendor_item_code="TFC-RP25-18", product_id="RNG-1001")


def _invoice(**kwargs) -> Invoice:
    """Create a bare invoice row for constraint tests."""
    defaults = {"source_filename": "x.json", "file_sha256": "0" * 64, "raw_content": "{}"}
    return Invoice.objects.create(**{**defaults, **kwargs})


def test_only_one_live_invoice_per_vendor_and_number(seeded):
    """The partial unique constraint behind duplicate detection (M2)."""
    _invoice(vendor_id="V01", invoice_number="10482", status=Invoice.Status.RECEIVED)

    # Normalized number collides even with different spacing and case.
    with pytest.raises(IntegrityError), transaction.atomic():
        _invoice(vendor_id="V01", invoice_number=" 10482 ", status=Invoice.Status.NEEDS_REVIEW)

    # Same number from another vendor is a different invoice (inv_04 vs inv_01).
    _invoice(vendor_id="V03", invoice_number="10482", status=Invoice.Status.RECEIVED)
    # Duplicate and rejected records do not block.
    _invoice(vendor_id="V01", invoice_number="10482", status=Invoice.Status.DUPLICATE)
    _invoice(vendor_id="V01", invoice_number="10482", status=Invoice.Status.REJECTED)
    # Unrecognized files have no vendor or number yet and never collide.
    _invoice(status=Invoice.Status.NEEDS_REVIEW)
    _invoice(status=Invoice.Status.NEEDS_REVIEW)


def test_costs_can_never_be_negative(seeded):
    """Default cost, PO unit cost and ledger cost are all non-negative."""
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.filter(sku="RNG-1001").update(default_cost=Decimal("-1"))
    with pytest.raises(IntegrityError), transaction.atomic():
        POLine.objects.filter(purchase_order_id="PO-2026-031").update(unit_cost=Decimal("-0.01"))
    with pytest.raises(IntegrityError), transaction.atomic():
        StockMovement.objects.create(
            kind="receipt", product_id="RNG-1001", quantity=Decimal("1"), total_cost=Decimal("-5")
        )


def test_the_admin_changes_nothing():
    """Reference data, stock, POs and invoices are view-only in the admin (services keep them consistent)."""
    for model, model_admin in admin.site._registry.items():
        if model._meta.app_label == "receiving":
            assert not model_admin.has_add_permission(None), model
            assert not model_admin.has_change_permission(None), model
            assert not model_admin.has_delete_permission(None), model
        for inline in model_admin.inlines:
            assert not inline(model, admin.site).has_change_permission(None), inline
