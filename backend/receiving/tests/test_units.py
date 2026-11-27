"""Unit conversion to the catalog unit (R2, M7)."""

from decimal import Decimal

import pytest

from receiving.units import Unit, convert, unit_from_alias


def test_dwt_to_gram_is_exact():
    """inv_10: 25 dwt is exactly 38.879346 g."""
    conversion = convert(Decimal("25"), Unit.DWT, Unit.GRAM)
    assert (conversion.quantity, conversion.exact) == (Decimal("38.879346"), True)


def test_gram_to_dwt_needs_rounding_and_says_so():
    """100 g in dwt is a non-terminating fraction: it is rounded and flagged as inexact."""
    conversion = convert(Decimal("100"), Unit.GRAM, Unit.DWT)
    assert conversion.exact is False
    assert conversion.quantity == Decimal("64.301493")


def test_troy_ounce_to_gram_has_seven_decimals_so_it_is_inexact():
    """1 ozt = 31.1034768 g does not fit 6 decimals; a person confirms the rounding."""
    assert convert(Decimal("1"), Unit.TROY_OZ, Unit.GRAM).exact is False
    assert convert(Decimal("10"), Unit.TROY_OZ, Unit.GRAM).quantity == Decimal("311.034768")


def test_count_and_mass_are_not_convertible():
    """Pieces cannot become grams."""
    assert convert(Decimal("1"), Unit.EACH, Unit.GRAM) is None


@pytest.mark.parametrize(
    "text, unit",
    [
        ("EA", Unit.EACH),
        ("pcs", Unit.EACH),
        ("G", Unit.GRAM),
        ("DWT", Unit.DWT),
        ("OZT", Unit.TROY_OZ),
        ("PR", None),
        ("PZ", None),
        ("", None),
        (None, None),
    ],
)
def test_only_exact_english_aliases_are_known(text, unit):
    """M7: PR (pair) and PZ (pezzo) go to a person."""
    assert unit_from_alias(text) == unit
