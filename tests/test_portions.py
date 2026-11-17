from pathlib import Path

import pytest

from asli.models import FoodEntry, PortionUnit
from asli.portions import DEFAULT_GRAMS, load_household_units, to_grams

HOUSEHOLD = {PortionUnit.BOWL: 150.0, PortionUnit.GLASS: 200.0}
REPO_ROOT = Path(__file__).resolve().parents[1]


def entry(serving_unit: PortionUnit, serving_grams: float | None) -> FoodEntry:
    return FoodEntry(
        code="X1", name="Test dish", serving_unit=serving_unit, serving_grams=serving_grams,
        energy_kcal=100, protein_g=5, carb_g=10, fat_g=3, fibre_g=2,
    )


def test_household_unit_uses_table_even_when_dish_has_serving_weight():
    portion = to_grams(PortionUnit.BOWL, 2, entry(PortionUnit.BOWL, 701.0), HOUSEHOLD)
    assert portion.grams == 300.0
    assert portion.reduced_confidence is False


def test_piece_of_countable_dish_uses_per_piece_weight():
    portion = to_grams(PortionUnit.PIECE, 2, entry(PortionUnit.PIECE, 36.0), HOUSEHOLD)
    assert portion.grams == 72.0
    assert portion.reduced_confidence is False


def test_serving_uses_databank_serving_weight():
    portion = to_grams(PortionUnit.SERVING, 1.5, entry(PortionUnit.BOWL, 120.0), HOUSEHOLD)
    assert portion.grams == pytest.approx(180.0)
    assert portion.reduced_confidence is False


def test_piece_of_non_countable_dish_falls_back_with_reduced_confidence():
    portion = to_grams(PortionUnit.PIECE, 1, entry(PortionUnit.BOWL, 120.0), HOUSEHOLD)
    assert portion.grams == 120.0
    assert portion.reduced_confidence is True


def test_unit_missing_from_table_falls_back_to_serving_weight():
    portion = to_grams(PortionUnit.PLATE, 1, entry(PortionUnit.PLATE, 300.0), HOUSEHOLD)
    assert portion.grams == 300.0
    assert portion.reduced_confidence is True


def test_no_serving_weight_uses_default_with_reduced_confidence():
    portion = to_grams(PortionUnit.SERVING, 2, entry(PortionUnit.SERVING, None), HOUSEHOLD)
    assert portion.grams == 2 * DEFAULT_GRAMS
    assert portion.reduced_confidence is True


def test_load_household_units_reads_committed_table():
    table = load_household_units(REPO_ROOT / "data" / "household_units.csv")
    assert table[PortionUnit.BOWL] == 150.0
    assert table[PortionUnit.CUP] == 240.0
    assert set(table) == {
        PortionUnit.BOWL, PortionUnit.PLATE, PortionUnit.CUP,
        PortionUnit.GLASS, PortionUnit.TABLESPOON, PortionUnit.TEASPOON,
    }
