"""Shared fixtures: reference data and helpers to submit sample files."""

from collections.abc import Callable

import pytest
from django.conf import settings

from receiving.models import Invoice
from receiving.seed import load_reference_data
from receiving.services import ingest_file


def sample_bytes(name: str) -> bytes:
    """Bytes of a sample invoice from data/invoices."""
    return (settings.DATA_DIR / "invoices" / name).read_bytes()


@pytest.fixture
def seeded(db) -> None:
    """A database loaded with data/ as shipped."""
    load_reference_data(settings.DATA_DIR)


@pytest.fixture
def ingest(seeded) -> Callable[..., Invoice]:
    """Submit a sample file (or given bytes under that name) and return the stored invoice."""

    def submit(name: str, data: bytes | None = None) -> Invoice:
        """Ingest and return the invoice."""
        return ingest_file(name, sample_bytes(name) if data is None else data).invoice

    return submit
