"""Domain models.

Reference data (vendors, catalog, vendor item map, purchase orders) is loaded by
`seed_data`. An invoice keeps the vendor's data exactly as received, next to the
system's interpretation of it. Staff edit only the interpretation (R5).

Note on `ordering = ["<fk>_id", ...]`: `<fk>_id` is the column Django creates for a
foreign key named `<fk>`. Ordering by it sorts by that column directly, without
joining the related table.
"""

from decimal import Decimal

from django.db import models
from django.db.models import Q

from .decimals import DECIMAL_PLACES, MAX_DIGITS
from .extraction.types import DocumentType, LineType
from .units import Unit


def decimal_field(**kwargs) -> models.DecimalField:
    """Every quantity and money amount. See decimals.py for why 15 digits."""
    return models.DecimalField(max_digits=MAX_DIGITS, decimal_places=DECIMAL_PLACES, **kwargs)


def choices(enum) -> list[tuple[str, str]]:
    """Django choices from a plain StrEnum, so the enum stays the single source of truth."""
    return [(member.value, member.value) for member in enum]


# --- Reference data -------------------------------------------------------------


class Vendor(models.Model):
    """A supplier the store buys from (data/vendors.csv)."""

    vendor_id = models.CharField(primary_key=True, max_length=16)
    name = models.CharField(max_length=200)
    country = models.CharField(max_length=2)
    currency = models.CharField(max_length=3)  # used when a CSV has no currency column (R7)
    ships_on_memo = models.BooleanField(default=False)

    class Meta:
        ordering = ["vendor_id"]

    def __str__(self) -> str:
        return f"{self.vendor_id} {self.name}"


class Product(models.Model):
    """A catalog SKU and its stock level (data/catalog.csv)."""

    sku = models.CharField(primary_key=True, max_length=32)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=50)
    unit = models.CharField(max_length=16, choices=choices(Unit))  # stock is kept in this unit
    serialized = models.BooleanField(default=False)  # each item has a certificate number
    default_cost = decimal_field()
    # Cached sum of this product's StockMovement rows. Only services change it,
    # inside a transaction that locks the row.
    on_hand = decimal_field(default=Decimal("0"))

    class Meta:
        ordering = ["sku"]
        constraints = [
            models.CheckConstraint(condition=Q(on_hand__gte=0), name="product_on_hand_non_negative"),
            models.CheckConstraint(condition=Q(default_cost__gte=0), name="product_default_cost_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.sku} {self.name}"


class VendorItem(models.Model):
    """A vendor's own item code mapped to a store SKU (data/vendor_sku_map.csv)."""

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="items")
    vendor_item_code = models.CharField(max_length=64)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="vendor_items")

    class Meta:
        ordering = ["vendor_id", "vendor_item_code"]
        constraints = [
            models.UniqueConstraint(fields=["vendor", "vendor_item_code"], name="vendor_item_code_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.vendor_id}:{self.vendor_item_code} -> {self.product_id}"


class PurchaseOrder(models.Model):
    """The store's order to a vendor (data/purchase_orders.json).

    The status follows its lines: open until something is received, received when
    every line is fully received.
    """

    class Status(models.TextChoices):
        """Where the order stands."""

        OPEN = "open"
        PARTIALLY_RECEIVED = "partially_received"
        RECEIVED = "received"

    po_number = models.CharField(primary_key=True, max_length=32)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="purchase_orders")
    order_date = models.DateField()
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ["po_number"]

    def __str__(self) -> str:
        return self.po_number


class POLine(models.Model):
    """One SKU on a purchase order: what was ordered, at what price, and how much has arrived.

    This is the store's side of the deal, not a copy of any invoice. Invoice lines
    are matched against it to check the agreed price (unit_cost) and the quantity
    still open (qty_ordered - qty_received). Approving an invoice increases
    qty_received here (the order's progress) and Product.on_hand (the stock);
    outcomes.json reports qty_received per PO line.
    """

    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="po_lines")
    qty_ordered = decimal_field()  # in the product's catalog unit
    # May exceed qty_ordered only when staff explicitly accept an over-receipt.
    qty_received = decimal_field(default=Decimal("0"))
    unit_cost = decimal_field()  # agreed price per catalog unit, in the PO currency

    class Meta:
        ordering = ["purchase_order_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["purchase_order", "product"], name="po_line_product_unique"),
            models.CheckConstraint(condition=Q(qty_ordered__gt=0), name="po_line_qty_ordered_positive"),
            models.CheckConstraint(condition=Q(qty_received__gte=0), name="po_line_qty_received_non_negative"),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="po_line_unit_cost_non_negative"),
        ]

    @property
    def remaining(self) -> Decimal:
        """Quantity still open on this line (negative after an accepted over-receipt)."""
        return self.qty_ordered - self.qty_received

    def __str__(self) -> str:
        return f"{self.purchase_order_id} {self.product_id}"


# --- Invoices -------------------------------------------------------------------


class Invoice(models.Model):
    """One uploaded vendor document: the raw file, its interpretation and its outcome."""

    class Status(models.TextChoices):
        """Outcome of an invoice; `pending` never leaves ingest."""

        PENDING = "pending"  # internal: exists only while ingest is deciding
        NEEDS_REVIEW = "needs_review"
        RECEIVED = "received"
        DUPLICATE = "duplicate"
        REJECTED = "rejected"
        CLOSED_NO_RECEIPT = "closed_no_receipt"

    # As received. Never changes after ingest.
    source_filename = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64, db_index=True)
    raw_content = models.TextField()
    raw_header = models.JSONField(default=dict, blank=True)  # canonical field -> text as in file
    # canonical field -> value as the file format's parser read it (decimals as exact text,
    # dates ISO); null where the text could not be read
    parsed_header = models.JSONField(default=dict, blank=True)
    parser_key = models.CharField(
        max_length=64,
        blank=True,
        help_text="Informational only: the parser that read the file at upload. No logic depends on it.",
    )

    # Interpretation. Staff may edit it during review.
    document_type = models.CharField(max_length=16, choices=choices(DocumentType), blank=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices")
    invoice_number = models.CharField(max_length=64, blank=True)
    invoice_number_norm = models.CharField(max_length=64, blank=True, editable=False)
    invoice_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices"
    )
    subtotal = decimal_field(null=True, blank=True)
    tax = decimal_field(null=True, blank=True)
    total = decimal_field(null=True, blank=True)
    notes = models.TextField(blank=True)  # vendor free text: displayed, never acted on
    edited_fields = models.JSONField(default=list, blank=True)  # fields a person changed

    # Outcome.
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    status_notes = models.TextField(blank=True)  # why the system reached this status
    duplicate_of = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="duplicates")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            # One live invoice per vendor and number, enforced by the database even
            # under concurrent uploads. Duplicates and rejected invoices do not count,
            # so a corrected file can be submitted again after a rejection.
            models.UniqueConstraint(
                fields=["vendor", "invoice_number_norm"],
                condition=~Q(status__in=["duplicate", "rejected"]) & ~Q(invoice_number_norm=""),
                name="live_invoice_number_unique_per_vendor",
            ),
        ]

    @staticmethod
    def normalize_number(number: str) -> str:
        """Duplicate-detection form of an invoice number (M2)."""
        return number.strip().upper()

    def save(self, *args, **kwargs) -> None:
        """Keep invoice_number_norm in sync with invoice_number."""
        self.invoice_number_norm = self.normalize_number(self.invoice_number)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "invoice_number" in update_fields:
            kwargs["update_fields"] = {*update_fields, "invoice_number_norm"}
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.source_filename} ({self.status})"


class InvoiceLine(models.Model):
    """One row of an invoice: the vendor's text and the system's interpretation of it."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveIntegerField()  # position in the document, from 1
    raw = models.JSONField(default=dict, blank=True)  # canonical field -> text as in file
    parsed = models.JSONField(default=dict, blank=True)  # canonical field -> value read by the format's parser

    # Interpretation.
    line_type = models.CharField(max_length=16, choices=choices(LineType), default=LineType.PRODUCT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True, related_name="invoice_lines")
    po_line = models.ForeignKey(POLine, on_delete=models.PROTECT, null=True, blank=True, related_name="invoice_lines")
    quantity = decimal_field(null=True, blank=True)  # in the product's catalog unit
    amount = decimal_field(null=True, blank=True)  # exact line total in the invoice currency
    serials = models.JSONField(default=list, blank=True)
    edited_fields = models.JSONField(default=list, blank=True)  # fields a person changed

    class Meta:
        ordering = ["invoice_id", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "line_no"], name="invoice_line_no_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_id}#{self.line_no}"


class Issue(models.Model):
    """Why an invoice needs a person. Recomputed on every validation."""

    class Kind(models.TextChoices):
        """How an issue affects approval."""

        TERMINAL = "terminal"  # approve impossible: reject (or close a memo)
        HARD = "hard"  # approve impossible until the interpretation is fixed
        SOFT = "soft"  # approve possible with an explicit "accept discrepancies"
        INFO = "info"  # does not block

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="issues")
    line = models.ForeignKey(InvoiceLine, on_delete=models.CASCADE, null=True, blank=True, related_name="issues")
    code = models.CharField(max_length=48)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    message = models.TextField()

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.kind}:{self.code}"


# --- Inventory ledger -----------------------------------------------------------


class StockMovement(models.Model):
    """Append-only stock ledger. Product.on_hand always equals the sum of its movements."""

    class Kind(models.TextChoices):
        """Why stock moved."""

        OPENING = "opening"  # stock on hand when the catalog was loaded
        RECEIPT = "receipt"  # received from an approved invoice

    kind = models.CharField(max_length=16, choices=Kind.choices)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    quantity = decimal_field()  # in the product's catalog unit
    total_cost = decimal_field(null=True, blank=True)  # exact line amount; unknown for opening stock
    currency = models.CharField(max_length=3, blank=True)
    invoice_line = models.ForeignKey(
        InvoiceLine, on_delete=models.PROTECT, null=True, blank=True, related_name="stock_movements"
    )
    po_line = models.ForeignKey(POLine, on_delete=models.PROTECT, null=True, blank=True, related_name="stock_movements")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            # Both kinds only add stock; returns would be a new, explicit kind.
            models.CheckConstraint(condition=Q(quantity__gt=0), name="stock_movement_quantity_positive"),
            models.CheckConstraint(
                condition=Q(total_cost__isnull=True) | Q(total_cost__gte=0),
                name="stock_movement_total_cost_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.product_id} {self.quantity}"


class SerialUnit(models.Model):
    """One certificate-tracked item. A serial number can be received only once."""

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="serial_units")
    serial_number = models.CharField(max_length=64, unique=True)
    stock_movement = models.ForeignKey(StockMovement, on_delete=models.PROTECT, related_name="serial_units")

    class Meta:
        ordering = ["serial_number"]

    def __str__(self) -> str:
        return self.serial_number


class AuditEvent(models.Model):
    """Who did what to an invoice, and when. Automatic receipt is `approved` by `system`."""

    class Action(models.TextChoices):
        """What happened to the invoice."""

        UPLOADED = "uploaded"
        EDITED = "edited"
        APPROVED = "approved"
        REJECTED = "rejected"
        CLOSED = "closed"

    SYSTEM = "system"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="audit_events")
    action = models.CharField(max_length=24, choices=Action.choices)
    actor = models.CharField(max_length=64)  # "system", or the staff member once auth exists
    payload = models.JSONField(default=dict, blank=True)  # before/after, accepted discrepancies
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.invoice_id} {self.action} by {self.actor}"
