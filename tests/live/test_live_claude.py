"""Calls the real Claude API. Costs money. Run with: ASLI_LIVE=1 uv run pytest -m live -v"""

import os

import pytest

from asli.models import Candidate, DishGuess, RecognitionStatus
from asli.recognizer import ClaudeRecognizer

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("ASLI_LIVE") != "1", reason="set ASLI_LIVE=1 to call the real API"),
]


def test_text_meal_is_recognized():
    result = ClaudeRecognizer().recognize(None, None, "2 rotis and a bowl of rajma")
    assert result.status is RecognitionStatus.OK
    words = " ".join(
        f"{d.name} {' '.join(d.alternative_names)}".lower() for d in result.dishes
    )
    assert "roti" in words or "chapati" in words
    assert "rajma" in words or "kidney" in words


def test_choose_picks_the_same_dish():
    guess = DishGuess(name="rajma", alternative_names=["kidney bean curry"], unit="bowl", quantity=1, confidence="high")
    candidates = [
        Candidate(code="ASC167", name="Sambar"),
        Candidate(code="ASC165", name="Kidney bean curry (Rajmah curry)"),
    ]
    assert ClaudeRecognizer().choose(guess, candidates) == "ASC165"
