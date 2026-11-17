"""Nutrients per dish with low/high ranges, and meal totals (spec 4.5)."""

from dataclasses import dataclass

from .models import Confidence, FoodEntry, Nutrients, NutrientRange

RANGE_FRACTION = {
    Confidence.HIGH: 0.15,
    Confidence.MEDIUM: 0.30,
    Confidence.LOW: 0.50,
}


@dataclass(frozen=True)
class DishNutrition:
    grams_low: float
    grams_high: float
    nutrients: NutrientRange


def nutrients_for(entry: FoodEntry, grams: float) -> Nutrients:
    return entry.per_100g().scaled(grams / 100.0)


def dish_nutrition(entry: FoodEntry, grams: float, confidence: Confidence) -> DishNutrition:
    fraction = RANGE_FRACTION[confidence]
    grams_low = grams * (1 - fraction)
    grams_high = grams * (1 + fraction)
    return DishNutrition(
        grams_low=grams_low,
        grams_high=grams_high,
        nutrients=NutrientRange(
            estimate=nutrients_for(entry, grams),
            low=nutrients_for(entry, grams_low),
            high=nutrients_for(entry, grams_high),
        ),
    )


def total(ranges: list[NutrientRange]) -> NutrientRange:
    result = NutrientRange(estimate=Nutrients(), low=Nutrients(), high=Nutrients())
    for r in ranges:
        result = NutrientRange(
            estimate=result.estimate + r.estimate,
            low=result.low + r.low,
            high=result.high + r.high,
        )
    return result
