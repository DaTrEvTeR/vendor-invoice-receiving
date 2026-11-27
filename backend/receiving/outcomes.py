"""results/outcomes.json: the fixed reporting interface defined by the brief."""

import json
from pathlib import Path
from typing import Any

from .decimals import plain
from .models import Invoice, POLine, Product, StockMovement
from .services import IngestResult, ingest_file


def sample_files(data_dir: Path) -> list[Path]:
    """The sample invoices in filename order."""
    return sorted(path for path in (data_dir / "invoices").iterdir() if path.is_file())


def submit_samples(data_dir: Path) -> list[IngestResult]:
    """Submit every sample invoice with no human review, as the brief prescribes."""
    return [ingest_file(path.name, path.read_bytes()) for path in sample_files(data_dir)]


def build_outcomes() -> dict[str, Any]:
    """The current state in the brief's format. Every number is a plain decimal string."""
    invoices = []
    for invoice in Invoice.objects.order_by("source_filename", "id"):
        movements = (
            StockMovement.objects.filter(kind=StockMovement.Kind.RECEIPT, invoice_line__invoice=invoice)
            .select_related("product", "po_line")
            .order_by("invoice_line__line_no", "id")
        )
        invoices.append(
            {
                "file": invoice.source_filename,
                "status": invoice.status,
                "notes": invoice.status_notes,
                "received_lines": [
                    {
                        "sku": movement.product_id,
                        "quantity": plain(movement.quantity),
                        "unit": movement.product.unit,
                        "po_number": movement.po_line.purchase_order_id if movement.po_line else None,
                    }
                    for movement in movements
                ],
            }
        )
    purchase_orders: dict[str, dict[str, str]] = {}
    for line in POLine.objects.order_by("purchase_order_id", "product_id"):
        purchase_orders.setdefault(line.purchase_order_id, {})[line.product_id] = plain(line.qty_received)
    return {
        "invoices": invoices,
        "inventory": {product.sku: plain(product.on_hand) for product in Product.objects.order_by("sku")},
        "purchase_orders": purchase_orders,
    }


def to_json(outcomes: dict[str, Any]) -> str:
    """Stable text: same state, same bytes."""
    return json.dumps(outcomes, indent=2, ensure_ascii=False) + "\n"
