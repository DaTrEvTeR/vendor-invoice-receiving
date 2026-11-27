"""Shared fixtures: reference data and the sample invoice files."""

import pytest
from django.conf import settings

from receiving.seed import load_reference_data


def sample_bytes(name: str) -> bytes:
    """Bytes of a sample invoice from data/invoices."""
    return (settings.DATA_DIR / "invoices" / name).read_bytes()


@pytest.fixture
def seeded(db) -> None:
    """A database loaded with data/ as shipped."""
    load_reference_data(settings.DATA_DIR)
