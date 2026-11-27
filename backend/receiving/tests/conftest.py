"""Shared test helpers: the sample invoice files."""

from django.conf import settings


def sample_bytes(name: str) -> bytes:
    """Bytes of a sample invoice from data/invoices."""
    return (settings.DATA_DIR / "invoices" / name).read_bytes()
