"""JSON shapes of the API.

Decimals travel as exact strings, never floats: quantities in plain notation ("38.879346",
"6"), money with cents when the cents are exact ("1866.25").
"""

from decimal import Decimal

from rest_framework import serializers

from ..decimals import DECIMAL_PLACES, MAX_DIGITS, money, plain
from ..extraction.types import DocumentType, LineType
from ..models import AuditEvent, Invoice, InvoiceLine, Issue, POLine, Product, PurchaseOrder, StockMovement, Vendor
from ..services import HEADER_FIELDS, LINE_FIELDS

Kind = Issue.Kind
UNIT_COST_QUANTUM = Decimal(1).scaleb(-DECIMAL_PLACES)


class Quantity(serializers.DecimalField):
    """An exact decimal within storage precision, shown in plain notation."""

    def __init__(self, **kwargs):
        """Storage precision: 15 digits, 6 after the point."""
        super().__init__(max_digits=MAX_DIGITS, decimal_places=DECIMAL_PLACES, **kwargs)

    def to_representation(self, value):
        """'6', '38.879346'."""
        return plain(value)


class Money(Quantity):
    """An exact amount, shown with cents when they are exact."""

    def to_representation(self, value):
        """'1866.25', '1866.208608'."""
        return money(value)


# --- Reference data -------------------------------------------------------------


class VendorSerializer(serializers.ModelSerializer):
    """A vendor."""

    class Meta:
        model = Vendor
        fields = ["vendor_id", "name", "country", "currency", "ships_on_memo"]


class ProductSerializer(serializers.ModelSerializer):
    """A catalog item and its stock."""

    default_cost = Money()
    on_hand = Quantity()

    class Meta:
        model = Product
        fields = ["sku", "name", "category", "unit", "serialized", "default_cost", "on_hand"]


class POLineSerializer(serializers.ModelSerializer):
    """A PO line with its progress, in the product's catalog unit."""

    sku = serializers.CharField(source="product_id")
    name = serializers.CharField(source="product.name")
    unit = serializers.CharField(source="product.unit")
    qty_ordered = Quantity()
    qty_received = Quantity()
    remaining = Quantity()
    unit_cost = Money()

    class Meta:
        model = POLine
        fields = [
            "id",
            "purchase_order",
            "sku",
            "name",
            "unit",
            "qty_ordered",
            "qty_received",
            "remaining",
            "unit_cost",
        ]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    """A purchase order and its lines."""

    vendor_name = serializers.CharField(source="vendor.name")
    lines = POLineSerializer(many=True)

    class Meta:
        model = PurchaseOrder
        fields = ["po_number", "vendor", "vendor_name", "order_date", "currency", "status", "lines"]


class StockMovementSerializer(serializers.ModelSerializer):
    """One ledger entry."""

    sku = serializers.CharField(source="product_id")
    quantity = Quantity()
    total_cost = Money()
    invoice = serializers.SerializerMethodField()
    po_number = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = ["id", "kind", "sku", "quantity", "total_cost", "currency", "invoice", "po_number", "created_at"]

    def get_invoice(self, obj: StockMovement) -> dict | None:
        """The invoice this receipt came from."""
        if obj.invoice_line is None:
            return None
        invoice = obj.invoice_line.invoice
        return {"id": invoice.pk, "source_filename": invoice.source_filename}

    def get_po_number(self, obj: StockMovement) -> str | None:
        """The PO the receipt counted against."""
        return obj.po_line.purchase_order_id if obj.po_line else None


# --- Invoices -------------------------------------------------------------------


class InvoiceListSerializer(serializers.ModelSerializer):
    """An invoice in the list: what it is and why it is in its status."""

    vendor_name = serializers.SerializerMethodField()
    total = Money()
    issue_counts = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "source_filename",
            "status",
            "document_type",
            "vendor",
            "vendor_name",
            "invoice_number",
            "invoice_date",
            "purchase_order",
            "currency",
            "total",
            "issue_counts",
            "created_at",
        ]

    def get_vendor_name(self, obj: Invoice) -> str | None:
        """The resolved vendor's name."""
        return obj.vendor.name if obj.vendor else None

    def get_issue_counts(self, obj: Invoice) -> dict[str, int]:
        """Open issues by kind."""
        counts = dict.fromkeys(Kind.values, 0)
        for issue in obj.issues.all():
            counts[issue.kind] += 1
        return counts


class InvoiceLineSerializer(serializers.ModelSerializer):
    """A line: the vendor's values (raw, parsed) next to the system's interpretation."""

    product_name = serializers.SerializerMethodField()
    product_unit = serializers.SerializerMethodField()
    serialized = serializers.SerializerMethodField()
    quantity = Quantity()
    amount = Money()
    unit_cost = serializers.SerializerMethodField()
    po_line = POLineSerializer()

    class Meta:
        model = InvoiceLine
        fields = [
            "id",
            "line_no",
            "line_type",
            "raw",
            "parsed",
            "product",
            "product_name",
            "product_unit",
            "serialized",
            "quantity",
            "amount",
            "unit_cost",
            "serials",
            "po_line",
            "edited_fields",
        ]

    def get_product_name(self, obj: InvoiceLine) -> str | None:
        """The SKU's name."""
        return obj.product.name if obj.product else None

    def get_product_unit(self, obj: InvoiceLine) -> str | None:
        """The SKU's catalog unit, in which `quantity` is given."""
        return obj.product.unit if obj.product else None

    def get_serialized(self, obj: InvoiceLine) -> bool:
        """Whether each item needs a certificate number."""
        return bool(obj.product and obj.product.serialized)

    def get_unit_cost(self, obj: InvoiceLine) -> str | None:
        """Cost per catalog unit, for display only (the ledger keeps the exact amount)."""
        if obj.amount is None or not obj.quantity:
            return None
        return money((obj.amount / obj.quantity).quantize(UNIT_COST_QUANTUM))


class IssueSerializer(serializers.ModelSerializer):
    """A reason the invoice needs a person, or context."""

    line_no = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = ["id", "code", "kind", "message", "line", "line_no"]

    def get_line_no(self, obj: Issue) -> int | None:
        """The line's position in the document."""
        return obj.line.line_no if obj.line else None


class AuditEventSerializer(serializers.ModelSerializer):
    """Who did what, when."""

    class Meta:
        model = AuditEvent
        fields = ["id", "action", "actor", "payload", "at"]


class InvoiceDetailSerializer(InvoiceListSerializer):
    """Everything the review screen shows."""

    subtotal = Money()
    tax = Money()
    duplicate_of = serializers.SerializerMethodField()
    lines = InvoiceLineSerializer(many=True)
    issues = IssueSerializer(many=True)
    audit_events = AuditEventSerializer(many=True)
    actions = serializers.SerializerMethodField()

    class Meta(InvoiceListSerializer.Meta):
        fields = [
            *InvoiceListSerializer.Meta.fields,
            "file_sha256",
            "parser_key",
            "status_notes",
            "decided_at",
            "duplicate_of",
            "subtotal",
            "tax",
            "notes",
            "edited_fields",
            "raw_header",
            "parsed_header",
            "raw_content",
            "lines",
            "issues",
            "audit_events",
            "actions",
        ]

    def get_duplicate_of(self, obj: Invoice) -> dict | None:
        """The invoice this one repeats."""
        original = obj.duplicate_of
        return {"id": original.pk, "source_filename": original.source_filename} if original else None

    def get_actions(self, obj: Invoice) -> dict[str, bool]:
        """What a person can do now, from the stored issues (approve validates again anyway)."""
        in_review = obj.status == Invoice.Status.NEEDS_REVIEW
        kinds = {issue.kind for issue in obj.issues.all()}
        return {
            "edit": in_review and bool(obj.raw_header),
            "approve": in_review and not kinds & {Kind.HARD, Kind.TERMINAL},
            "needs_confirmation": Kind.SOFT in kinds,
            "reject": in_review,
            "close": in_review and obj.document_type in (DocumentType.MEMO, DocumentType.CREDIT_MEMO),
        }


# --- Input ----------------------------------------------------------------------


class EditSerializer(serializers.Serializer):
    """Common rule: an edit must set or revert something."""

    def validate(self, attrs):
        """Refuse an empty edit."""
        if not attrs.get("revert") and not set(attrs) - {"revert"}:
            raise serializers.ValidationError("Nothing to change.")
        return attrs


class HeaderEditSerializer(EditSerializer):
    """Header fields a person may correct (R5). `revert` hands fields back to the system."""

    document_type = serializers.ChoiceField(choices=[t.value for t in DocumentType], required=False)
    invoice_number = serializers.CharField(max_length=64, required=False)
    invoice_date = serializers.DateField(required=False, allow_null=True)
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all(), required=False, allow_null=True)
    purchase_order = serializers.PrimaryKeyRelatedField(
        queryset=PurchaseOrder.objects.all(), required=False, allow_null=True
    )
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False)
    subtotal = Money(required=False, allow_null=True)
    tax = Money(required=False, allow_null=True)
    total = Money(required=False, allow_null=True)
    revert = serializers.ListField(child=serializers.ChoiceField(choices=HEADER_FIELDS), required=False)


class LineEditSerializer(EditSerializer):
    """Line fields a person may correct (R5); the quantity is in the SKU's catalog unit."""

    line_type = serializers.ChoiceField(choices=[t.value for t in LineType], required=False)
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), required=False, allow_null=True)
    quantity = Quantity(required=False, allow_null=True)
    amount = Money(required=False, allow_null=True)
    serials = serializers.ListField(child=serializers.CharField(max_length=64), required=False)
    revert = serializers.ListField(child=serializers.ChoiceField(choices=LINE_FIELDS), required=False)


class ApproveSerializer(serializers.Serializer):
    """Approving with discrepancies needs an explicit yes (R5a)."""

    accept_discrepancies = serializers.BooleanField(default=False)


class ReasonSerializer(serializers.Serializer):
    """An optional reason for rejecting or closing."""

    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
