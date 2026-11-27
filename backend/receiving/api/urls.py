"""API routes under /api/."""

from django.urls import re_path
from rest_framework.routers import SimpleRouter

from . import views


class OptionalSlashRouter(SimpleRouter):
    """Routes match with or without a trailing slash, so proxies that drop it still work."""

    def __init__(self):
        """Same routes as SimpleRouter, with an optional final slash."""
        super().__init__()
        self.trailing_slash = "/?"


router = OptionalSlashRouter()
router.register("invoices", views.InvoiceViewSet, basename="invoice")
router.register("vendors", views.VendorViewSet)
router.register("products", views.ProductViewSet)
router.register("purchase-orders", views.PurchaseOrderViewSet)
router.register("stock-movements", views.StockMovementViewSet)

urlpatterns = [re_path(r"^health/?$", views.health, name="health"), *router.urls]
