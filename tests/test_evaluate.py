import pytest

from asli.evaluate import MealScore, TruthDish, TruthMeal, load_meals, score_meal, summarize
from asli.models import (
    AnalysisResult,
    AnalysisStatus,
    AnalyzedDish,
    Candidate,
    Nutrients,
    NutrientRange,
)


def predicted(code, grams):
    return AnalyzedDish(
        name=code, status="matched", match=Candidate(code=code, name=code),
        unit="bowl", quantity=1, grams=grams, confidence="high",
    )


def prediction(dishes, protein):
    n = Nutrients(protein_g=protein)
    return AnalysisResult(
        status=AnalysisStatus.OK, dishes=dishes, totals=NutrientRange(estimate=n, low=n, high=n)
    )


def test_score_meal(food_db):
    truth = TruthMeal(id="m1", dishes=[TruthDish(code="ASC096", grams=72), TruthDish(code="ASC165", grams=200)])
    # truth protein: 72 g * 8/100 + 200 g * 6/100 = 5.76 + 12 = 17.76
    pred = prediction([predicted("ASC096", 36)], protein=2.88)
    score = score_meal(pred, truth, food_db)
    assert score.dishes_found == 1
    assert score.dishes_total == 2
    assert score.portion_errors == [pytest.approx(0.5)]
    assert score.protein_error_g == pytest.approx(17.76 - 2.88)


def test_score_meal_with_no_prediction(food_db):
    truth = TruthMeal(id="m2", dishes=[TruthDish(code="ASC096", grams=36)])
    score = score_meal(AnalysisResult(status=AnalysisStatus.ERROR), truth, food_db)
    assert score.dishes_found == 0
    assert score.protein_error_g == pytest.approx(2.88)


def test_summarize():
    scores = [
        MealScore("a", 1, 2, [0.5], 4.0),
        MealScore("b", 2, 2, [0.1, 0.3], 2.0),
    ]
    summary = summarize(scores)
    assert summary.meals == 2
    assert summary.identification_accuracy == pytest.approx(3 / 4)
    assert summary.mean_portion_error == pytest.approx(0.3)
    assert summary.mean_protein_error_g == pytest.approx(3.0)


def test_load_meals(tmp_path):
    path = tmp_path / "meals.jsonl"
    path.write_text(
        '{"id": "x", "image": null, "text": "dal", "dishes": [{"code": "ASC165", "grams": 150}]}\n\n',
        encoding="utf-8",
    )
    meals = load_meals(path)
    assert [m.id for m in meals] == ["x"]
    assert meals[0].dishes[0].grams == 150
