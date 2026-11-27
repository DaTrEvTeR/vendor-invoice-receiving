"""View-only admin for inspecting data.

Reference data comes from data/ (seed_data). Stock, PO progress and invoices change
only through services (ingest, review, approve), which keep the ledger and the audit
trail consistent. Editing a catalog unit or a PO line here would silently change the
meaning of stock and receipts already recorded, so the admin edits nothing.
"""

from django.contrib import admin

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


class ReadOnlyAdmin(admin.ModelAdmin):
    """View-only admin for rows that only services may change."""

    def has_add_permission(self, request, obj=None):
        """No adding."""
        return False

    def has_change_permission(self, request, obj=None):
        """No editing."""
        return False

    def has_delete_permission(self, request, obj=None):
        """No deleting."""
        return False


@admin.register(Vendor)
class VendorAdmin(ReadOnlyAdmin):
    """Vendors."""

    list_display = ["vendor_id", "name", "country", "currency", "ships_on_memo"]


@admin.register(Product)
class ProductAdmin(ReadOnlyAdmin):
    """Catalog with stock (on_hand follows the ledger)."""

    list_display = ["sku", "name", "category", "unit", "serialized", "default_cost", "on_hand"]
    list_filter = ["category", "unit", "serialized"]
    search_fields = ["sku", "name"]


@admin.register(VendorItem)
class VendorItemAdmin(ReadOnlyAdmin):
    """Vendor item code to SKU map."""

    list_display = ["vendor", "vendor_item_code", "product"]
    list_filter = ["vendor"]
    search_fields = ["vendor_item_code", "product__sku"]


class POLineInline(admin.TabularInline):
    """PO lines, view-only."""

    model = POLine
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        """No adding."""
        return False

    def has_change_permission(self, request, obj=None):
        """No editing."""
        return False


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(ReadOnlyAdmin):
    """Purchase orders; the status is derived from the lines."""

    list_display = ["po_number", "vendor", "order_date", "currency", "status"]
    list_filter = ["status", "vendor"]
    inlines = [POLineInline]


class InvoiceLineInline(admin.TabularInline):
    """Invoice lines, view-only."""

    model = InvoiceLine
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        """No adding."""
        return False

    def has_change_permission(self, request, obj=None):
        """No editing."""
        return False


class IssueInline(admin.TabularInline):
    """Issues, view-only."""

    model = Issue
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        """No adding."""
        return False

    def has_change_permission(self, request, obj=None):
        """No editing."""
        return False


@admin.register(Invoice)
class InvoiceAdmin(ReadOnlyAdmin):
    """Invoices, view-only: review happens through the API."""

    list_display = ["id", "source_filename", "vendor", "invoice_number", "document_type", "status", "created_at"]
    list_filter = ["status", "document_type", "vendor"]
    search_fields = ["source_filename", "invoice_number"]
    inlines = [InvoiceLineInline, IssueInline]


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    """The stock ledger, view-only."""

    list_display = ["id", "kind", "product", "quantity", "total_cost", "currency", "invoice_line", "created_at"]
    list_filter = ["kind"]


@admin.register(SerialUnit)
class SerialUnitAdmin(ReadOnlyAdmin):
    """Received certificates, view-only."""

    list_display = ["serial_number", "product", "stock_movement"]
    search_fields = ["serial_number"]


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    """Audit trail, view-only."""

    list_display = ["id", "invoice", "action", "actor", "at"]
    list_filter = ["action"]
