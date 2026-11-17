import pytest

from asli.calculator import dish_nutrition, nutrients_for, total
from asli.models import Confidence, FoodEntry, Nutrients, NutrientRange, PortionUnit

CHAPATI = FoodEntry(
    code="ASC096", name="Chapati/Roti", serving_unit=PortionUnit.PIECE, serving_grams=36.0,
    energy_kcal=250, protein_g=8, carb_g=45, fat_g=4, fibre_g=5,
)


def test_nutrients_scale_with_grams():
    n = nutrients_for(CHAPATI, 36.0)
    assert n.protein_g == pytest.approx(2.88)
    assert n.energy_kcal == pytest.approx(90.0)


@pytest.mark.parametrize(
    "confidence, low_factor, high_factor",
    [(Confidence.HIGH, 0.85, 1.15), (Confidence.MEDIUM, 0.70, 1.30), (Confidence.LOW, 0.50, 1.50)],
)
def test_dish_range_widens_with_lower_confidence(confidence, low_factor, high_factor):
    result = dish_nutrition(CHAPATI, 100.0, confidence)
    assert result.grams_low == pytest.approx(100.0 * low_factor)
    assert result.grams_high == pytest.approx(100.0 * high_factor)
    assert result.nutrients.estimate.protein_g == pytest.approx(8.0)
    assert result.nutrients.low.protein_g == pytest.approx(8.0 * low_factor)
    assert result.nutrients.high.protein_g == pytest.approx(8.0 * high_factor)


def test_total_sums_each_bound():
    a = dish_nutrition(CHAPATI, 100.0, Confidence.HIGH).nutrients
    b = dish_nutrition(CHAPATI, 50.0, Confidence.LOW).nutrients
    t = total([a, b])
    assert t.estimate.protein_g == pytest.approx(8.0 + 4.0)
    assert t.low.protein_g == pytest.approx(8.0 * 0.85 + 4.0 * 0.5)
    assert t.high.protein_g == pytest.approx(8.0 * 1.15 + 4.0 * 1.5)


def test_total_of_nothing_is_zero():
    assert total([]) == NutrientRange(estimate=Nutrients(), low=Nutrients(), high=Nutrients())
