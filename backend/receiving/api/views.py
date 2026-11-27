"""HTTP endpoints. Each one validates input, calls one use case and returns the result."""

from django.conf import settings
from django.db.models import Prefetch
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import UnsupportedMediaType, ValidationError
from rest_framework.response import Response

from .. import services
from ..models import AuditEvent, Invoice, InvoiceLine, Issue, Product, PurchaseOrder, StockMovement, Vendor
from . import serializers as s

# No login yet (dev-only, see DECISIONS.md): every action through the API is recorded as "staff".
ACTOR = "staff"


def json_body(request) -> dict:
    """The body of a decision request, which must be sent as JSON.

    A browser sends a JSON request from another website only after a CORS preflight,
    which this API never grants. Until there is a login (see DECISIONS.md, Security),
    this keeps another site the reviewer visits from approving or rejecting invoices
    through a plain form post.
    """
    if request.content_type.split(";")[0].strip().lower() != "application/json":
        raise UnsupportedMediaType(request.content_type or "none", "Send the request body as application/json.")
    return request.data


@api_view(["GET"])
def health(request):
    """The server answers requests. Used by the container healthcheck; touches no data."""
    return Response({"status": "ok"})


class InvoiceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Upload, list, review, edit and decide invoices."""

    def get_queryset(self):
        """Invoices, newest first, with what the serializers read."""
        queryset = Invoice.objects.select_related("vendor").order_by("-id")
        if self.action == "list":
            return queryset.prefetch_related("issues")
        return queryset.select_related("duplicate_of").prefetch_related(
            Prefetch(
                "lines",
                queryset=InvoiceLine.objects.select_related("product", "po_line__product").order_by("line_no"),
            ),
            Prefetch("issues", queryset=Issue.objects.select_related("line").order_by("id")),
            Prefetch("audit_events", queryset=AuditEvent.objects.order_by("id")),
        )

    def get_serializer_class(self):
        """Short rows for the list, everything for one invoice."""
        return s.InvoiceListSerializer if self.action == "list" else s.InvoiceDetailSerializer

    def invoice_data(self, invoice_id: int, **extra) -> dict:
        """The invoice as the review screen needs it, freshly loaded."""
        data = s.InvoiceDetailSerializer(self.get_queryset().get(pk=invoice_id)).data
        return {**data, **extra}

    def create(self, request):
        """Submit a vendor file (multipart field `file`). The same bytes again return the stored invoice."""
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Attach the invoice file in the 'file' field."})
        if upload.size > settings.MAX_UPLOAD_BYTES:  # checked before reading the file into memory
            raise services.UploadRejected(f"The file is larger than {settings.MAX_UPLOAD_BYTES} bytes.")
        result = services.ingest_file(upload.name, upload.read())
        return Response(
            self.invoice_data(result.invoice.pk, already_uploaded=not result.created),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )

    def partial_update(self, request, pk=None):
        """Correct the header interpretation; the invoice is validated again."""
        edit = s.HeaderEditSerializer(data=request.data)
        edit.is_valid(raise_exception=True)
        changes = dict(edit.validated_data)
        revert = changes.pop("revert", [])
        invoice = services.edit_invoice(int(pk), ACTOR, changes, revert)
        return Response(self.invoice_data(invoice.pk))

    @action(detail=True, methods=["patch"], url_path=r"lines/(?P<line_id>[0-9]+)")
    def edit_line(self, request, pk=None, line_id=None):
        """Correct one line's interpretation; the invoice is validated again."""
        edit = s.LineEditSerializer(data=request.data)
        edit.is_valid(raise_exception=True)
        changes = dict(edit.validated_data)
        revert = changes.pop("revert", [])
        invoice = services.edit_line(int(pk), int(line_id), ACTOR, changes, revert)
        return Response(self.invoice_data(invoice.pk))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Receive the invoice into stock. Discrepancies must be accepted explicitly."""
        body = s.ApproveSerializer(data=json_body(request))
        body.is_valid(raise_exception=True)
        invoice = services.approve(int(pk), ACTOR, body.validated_data["accept_discrepancies"])
        return Response(self.invoice_data(invoice.pk))

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """Refuse the invoice; nothing is received."""
        body = s.ReasonSerializer(data=json_body(request))
        body.is_valid(raise_exception=True)
        invoice = services.reject(int(pk), ACTOR, body.validated_data["reason"])
        return Response(self.invoice_data(invoice.pk))

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Close a MEMO or CREDIT_MEMO without receipt."""
        body = s.ReasonSerializer(data=json_body(request))
        body.is_valid(raise_exception=True)
        invoice = services.close(int(pk), ACTOR, body.validated_data["reason"])
        return Response(self.invoice_data(invoice.pk))


class VendorViewSet(viewsets.ReadOnlyModelViewSet):
    """Vendors, for choosing one during review."""

    queryset = Vendor.objects.order_by("vendor_id")
    serializer_class = s.VendorSerializer


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """The catalog with current stock."""

    queryset = Product.objects.order_by("sku")
    serializer_class = s.ProductSerializer


class PurchaseOrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Purchase orders with ordered, received and remaining quantities."""

    queryset = PurchaseOrder.objects.select_related("vendor").prefetch_related("lines__product").order_by("po_number")
    serializer_class = s.PurchaseOrderSerializer


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    """The stock ledger, newest first."""

    queryset = StockMovement.objects.select_related("invoice_line__invoice", "po_line").order_by("-id")
    serializer_class = s.StockMovementSerializer
