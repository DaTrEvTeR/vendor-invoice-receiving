"""Units of measure: the catalog's units, vendor aliases and exact conversions (R2, M7).

Pure Python, no database access.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .decimals import DECIMAL_PLACES


class Unit(StrEnum):
    """Units the store keeps stock in (the catalog's `unit` column)."""

    EACH = "each"
    GRAM = "gram"
    DWT = "dwt"
    TROY_OZ = "troy_oz"


# Exact definitions of the troy system in grams, so conversions are arithmetic, not estimates.
GRAMS_PER_UNIT: dict[Unit, Decimal] = {
    Unit.GRAM: Decimal("1"),
    Unit.DWT: Decimal("1.55517384"),
    Unit.TROY_OZ: Decimal("31.1034768"),
}

# Only unambiguous English spellings (M7). "PR" (pair) and "PZ" (Italian "pezzo") are
# deliberately absent: what they mean in catalog units is for a person to decide.
UOM_ALIASES: dict[str, Unit] = {
    "EA": Unit.EACH,
    "EACH": Unit.EACH,
    "PC": Unit.EACH,
    "PCS": Unit.EACH,
    "G": Unit.GRAM,
    "GR": Unit.GRAM,
    "GRAM": Unit.GRAM,
    "GRAMS": Unit.GRAM,
    "DWT": Unit.DWT,
    "OZT": Unit.TROY_OZ,
}

_QUANTUM = Decimal(1).scaleb(-DECIMAL_PLACES)


@dataclass(frozen=True)
class Conversion:
    """A quantity converted to the catalog unit, rounded to storage precision.

    `exact` is False when rounding changed the value (for example grams to dwt);
    a person must then confirm it.
    """

    quantity: Decimal
    exact: bool
    from_unit: Unit
    to_unit: Unit

    @property
    def changed_unit(self) -> bool:
        """True when the vendor's unit differs from the catalog unit."""
        return self.from_unit != self.to_unit


def unit_from_alias(text: str | None) -> Unit | None:
    """Map a vendor's unit text to a catalog unit; None if it is not an exact known alias."""
    if text is None:
        return None
    return UOM_ALIASES.get(text.strip().upper())


def convert(quantity: Decimal, from_unit: Unit, to_unit: Unit) -> Conversion | None:
    """Convert `quantity` between units; None when the units are not comparable (each vs gram)."""
    if from_unit == to_unit:
        return Conversion(quantity, True, from_unit, to_unit)
    if from_unit not in GRAMS_PER_UNIT or to_unit not in GRAMS_PER_UNIT:
        return None
    grams = quantity * GRAMS_PER_UNIT[from_unit]
    rounded = (grams / GRAMS_PER_UNIT[to_unit]).quantize(_QUANTUM)
    # Exact when the rounded value converts back to exactly the same mass.
    exact = rounded * GRAMS_PER_UNIT[to_unit] == grams
    return Conversion(rounded, exact, from_unit, to_unit)
