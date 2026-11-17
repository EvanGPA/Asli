import pytest
from pydantic import ValidationError

from asli.models import Confidence, DishGuess, FoodEntry, Nutrients, PortionUnit


def test_confidence_lowered_steps_down_and_stops_at_low():
    assert Confidence.HIGH.lowered() is Confidence.MEDIUM
    assert Confidence.MEDIUM.lowered() is Confidence.LOW
    assert Confidence.LOW.lowered() is Confidence.LOW


def test_nutrients_add_and_scale():
    a = Nutrients(energy_kcal=100, protein_g=4, carb_g=10, fat_g=2, fibre_g=1)
    b = Nutrients(energy_kcal=50, protein_g=1, carb_g=5, fat_g=1, fibre_g=0)
    total = a + b
    assert total.protein_g == 5
    assert total.energy_kcal == 150
    assert a.scaled(0.5).carb_g == 5


def test_dish_guess_rejects_non_positive_quantity():
    with pytest.raises(ValidationError):
        DishGuess(name="dal", unit="bowl", quantity=0, confidence="high")


def test_food_entry_per_100g():
    entry = FoodEntry(
        code="X1", name="Test", serving_unit=PortionUnit.BOWL, serving_grams=150,
        energy_kcal=120, protein_g=6, carb_g=15, fat_g=4, fibre_g=5,
    )
    assert entry.per_100g() == Nutrients(energy_kcal=120, protein_g=6, carb_g=15, fat_g=4, fibre_g=5)
