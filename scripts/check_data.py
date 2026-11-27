"""Load and print the sample data files. Run from the repo root: python scripts/check_data.py"""

import csv
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

for name in ("catalog.csv", "vendors.csv", "vendor_sku_map.csv"):
    with open(DATA / name, newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"{name}: {len(rows)} rows, columns {list(rows[0])}")

pos = json.loads((DATA / "purchase_orders.json").read_text())
print(
    f"purchase_orders.json: {len(pos)} POs, {sum(len(p['lines']) for p in pos)} lines"
)
print("invoices:", sorted(p.name for p in (DATA / "invoices").iterdir()))
