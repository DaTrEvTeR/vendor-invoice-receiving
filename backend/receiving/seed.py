"""Load the reference data shipped in data/ (catalog, vendors, item map, POs).

The files are the starting state and are never modified: everything that happens
later is written to the database only. Values are parsed strictly; anything
unexpected stops the load instead of being guessed.
"""

import csv
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.db import transaction

from .decimals import fits_storage
from .models import (
    AuditEvent,
    Invoice,
    InvoiceLine,
    Issue,
    POLine,
    Product,
    PurchaseOrder,
    SerialUnit,
    StockMovement,
    Vendor,
    VendorItem,
)
from .units import Unit


class SeedError(Exception):
    """The reference data contains something the loader will not guess about."""


def _decimal(value: str, where: str) -> Decimal:
    """A decimal that fits storage precision exactly."""
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise SeedError(f"{where}: {value!r} is not a decimal number") from None
    if not fits_storage(result):
        raise SeedError(f"{where}: {value!r} does not fit the stored precision")
    return result


def _bool(value: str, where: str) -> bool:
    """Only the literal strings 'true' and 'false'."""
    if value not in ("true", "false"):
        raise SeedError(f"{where}: expected 'true' or 'false', got {value!r}")
    return value == "true"


def _read_csv(path: Path) -> list[dict[str, str]]:
    """All rows of a CSV file with a header row."""
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def wipe_all() -> None:
    """Delete every row this app owns, children first."""
    AuditEvent.objects.all().delete()
    SerialUnit.objects.all().delete()
    StockMovement.objects.all().delete()
    Issue.objects.all().delete()
    InvoiceLine.objects.all().delete()
    Invoice.objects.update(duplicate_of=None)
    Invoice.objects.all().delete()
    POLine.objects.all().delete()
    PurchaseOrder.objects.all().delete()
    VendorItem.objects.all().delete()
    Product.objects.all().delete()
    Vendor.objects.all().delete()


@transaction.atomic
def load_reference_data(data_dir: Path) -> dict[str, int]:
    """Load data/ into an empty database. Returns row counts per entity."""
    vendors = [
        Vendor(
            vendor_id=row["vendor_id"],
            name=row["name"],
            country=row["country"],
            currency=row["currency"],
            ships_on_memo=_bool(row["ships_on_memo"], f"vendors.csv {row['vendor_id']}"),
        )
        for row in _read_csv(data_dir / "vendors.csv")
    ]
    Vendor.objects.bulk_create(vendors)

    products = []
    for row in _read_csv(data_dir / "catalog.csv"):
        where = f"catalog.csv {row['sku']}"
        if row["unit"] not in {unit.value for unit in Unit}:
            raise SeedError(f"{where}: unknown unit {row['unit']!r}")
        products.append(
            Product(
                sku=row["sku"],
                name=row["name"],
                category=row["category"],
                unit=row["unit"],
                serialized=_bool(row["serialized"], where),
                default_cost=_decimal(row["default_cost"], where),
                on_hand=_decimal(row["on_hand"], where),
            )
        )
    Product.objects.bulk_create(products)
    # Opening balances, so that on_hand is always explained by the ledger.
    StockMovement.objects.bulk_create(
        StockMovement(kind=StockMovement.Kind.OPENING, product=p, quantity=p.on_hand) for p in products if p.on_hand
    )

    items = [
        VendorItem(vendor_id=row["vendor_id"], vendor_item_code=row["vendor_item_code"], product_id=row["sku"])
        for row in _read_csv(data_dir / "vendor_sku_map.csv")
    ]
    VendorItem.objects.bulk_create(items)

    raw_pos = json.loads((data_dir / "purchase_orders.json").read_text(encoding="utf-8"), parse_float=Decimal)
    po_lines = []
    for raw_po in raw_pos:
        where = f"purchase_orders.json {raw_po['po_number']}"
        if raw_po["status"] not in PurchaseOrder.Status.values:
            raise SeedError(f"{where}: unknown status {raw_po['status']!r}")
        po = PurchaseOrder.objects.create(
            po_number=raw_po["po_number"],
            vendor_id=raw_po["vendor_id"],
            order_date=date.fromisoformat(raw_po["order_date"]),
            currency=raw_po["currency"],
            status=raw_po["status"],
        )
        for raw_line in raw_po["lines"]:
            line_where = f"{where} {raw_line['sku']}"
            po_lines.append(
                POLine(
                    purchase_order=po,
                    product_id=raw_line["sku"],
                    qty_ordered=_decimal(str(raw_line["qty_ordered"]), line_where),
                    qty_received=_decimal(str(raw_line["qty_received"]), line_where),
                    unit_cost=_decimal(str(raw_line["unit_cost"]), line_where),
                )
            )
    POLine.objects.bulk_create(po_lines)

    return {
        "vendors": len(vendors),
        "products": len(products),
        "vendor_items": len(items),
        "purchase_orders": len(raw_pos),
        "po_lines": len(po_lines),
    }
