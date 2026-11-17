"""Household units to grams (spec 4.4)."""

import csv
from dataclasses import dataclass
from pathlib import Path

from .models import FoodEntry, PortionUnit

DEFAULT_GRAMS = 100.0


@dataclass(frozen=True)
class Portion:
    grams: float
    reduced_confidence: bool


def load_household_units(path: str | Path) -> dict[PortionUnit, float]:
    with open(path, newline="", encoding="utf-8") as f:
        return {PortionUnit(row["unit"]): float(row["grams"]) for row in csv.DictReader(f)}


def to_grams(
    unit: PortionUnit, quantity: float, entry: FoodEntry, household: dict[PortionUnit, float]
) -> Portion:
    # Rule 1: containers and spoons use the household table.
    if unit in household:
        return Portion(quantity * household[unit], reduced_confidence=False)
    if entry.serving_grams:
        # Rules 2 and 3: per-piece weight for countable dishes, serving weight for "serving".
        exact = unit == PortionUnit.SERVING or (
            unit == PortionUnit.PIECE and entry.serving_unit == PortionUnit.PIECE
        )
        # Rule 4: any other combination uses the serving weight with reduced confidence.
        return Portion(quantity * entry.serving_grams, reduced_confidence=not exact)
    return Portion(quantity * DEFAULT_GRAMS, reduced_confidence=True)
