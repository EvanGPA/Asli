"""Score the engine against weighed meals (spec section 7)."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from .food_db import FoodDB
from .models import AnalysisResult

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


class TruthDish(BaseModel):
    code: str
    grams: float


class TruthMeal(BaseModel):
    id: str
    image: str | None = None
    text: str | None = None
    dishes: list[TruthDish]


@dataclass
class MealScore:
    meal_id: str
    dishes_found: int
    dishes_total: int
    portion_errors: list[float]
    protein_error_g: float


@dataclass
class Summary:
    meals: int
    identification_accuracy: float
    mean_portion_error: float
    mean_protein_error_g: float


def load_meals(path: Path) -> list[TruthMeal]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [TruthMeal.model_validate_json(line) for line in lines if line.strip()]


def score_meal(prediction: AnalysisResult, truth: TruthMeal, db: FoodDB) -> MealScore:
    predicted_grams: dict[str, float] = defaultdict(float)
    for dish in prediction.dishes:
        if dish.match is not None and dish.grams is not None:
            predicted_grams[dish.match.code] += dish.grams

    found = 0
    portion_errors: list[float] = []
    true_protein = 0.0
    for dish in truth.dishes:
        entry = db.get(dish.code)
        if entry is None:
            raise ValueError(f"Meal {truth.id}: unknown food code {dish.code}")
        true_protein += entry.protein_g * dish.grams / 100.0
        if dish.code in predicted_grams:
            found += 1
            portion_errors.append(abs(predicted_grams[dish.code] - dish.grams) / dish.grams)

    predicted_protein = prediction.totals.estimate.protein_g if prediction.totals else 0.0
    return MealScore(
        meal_id=truth.id,
        dishes_found=found,
        dishes_total=len(truth.dishes),
        portion_errors=portion_errors,
        protein_error_g=abs(predicted_protein - true_protein),
    )


def summarize(scores: list[MealScore]) -> Summary:
    total_dishes = sum(s.dishes_total for s in scores)
    errors = [e for s in scores for e in s.portion_errors]
    return Summary(
        meals=len(scores),
        identification_accuracy=sum(s.dishes_found for s in scores) / total_dishes if total_dishes else 0.0,
        mean_portion_error=sum(errors) / len(errors) if errors else 0.0,
        mean_protein_error_g=sum(s.protein_error_g for s in scores) / len(scores) if scores else 0.0,
    )


def main(argv: list[str] | None = None) -> None:
    from .config import load_settings
    from .engine import build_engine

    parser = argparse.ArgumentParser(description="Score the engine on weighed meals (calls the real AI API).")
    parser.add_argument("meals", type=Path)
    args = parser.parse_args(argv)

    settings = load_settings()
    engine = build_engine(settings)
    db = FoodDB(settings.food_db_path)
    scores = []
    for meal in load_meals(args.meals):
        image = media_type = None
        if meal.image:
            image_path = args.meals.parent / meal.image
            image = image_path.read_bytes()
            media_type = MEDIA_TYPES[image_path.suffix.lower()]
        result = engine.analyze(image, media_type, meal.text)
        score = score_meal(result, meal, db)
        scores.append(score)
        print(
            f"{meal.id}: status={result.status.value} found={score.dishes_found}/{score.dishes_total} "
            f"protein_error={score.protein_error_g:.1f} g"
        )

    summary = summarize(scores)
    print(
        f"\n{summary.meals} meals | dish identification {summary.identification_accuracy:.0%} | "
        f"mean portion error {summary.mean_portion_error:.0%} | "
        f"mean protein error {summary.mean_protein_error_g:.1f} g"
    )


if __name__ == "__main__":
    main()
