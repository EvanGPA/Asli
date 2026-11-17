"""Orchestrates recognition, matching, portions and nutrients for one meal."""

from .calculator import dish_nutrition, total
from .config import Settings
from .food_db import FoodDB
from .interfaces import Recognizer, RecognizerError
from .matcher import Matcher
from .models import (
    AnalysisResult,
    AnalysisStatus,
    AnalyzedDish,
    Candidate,
    Confidence,
    DishGuess,
    PortionUnit,
    RecognitionStatus,
)
from .portions import load_household_units, to_grams
from .unmatched_log import UnmatchedLog


class Engine:
    def __init__(
        self,
        recognizer: Recognizer,
        matcher: Matcher,
        household: dict[PortionUnit, float],
        unmatched_log: UnmatchedLog,
    ):
        self._recognizer = recognizer
        self._matcher = matcher
        self._household = household
        self._unmatched = unmatched_log

    def analyze(
        self, image: bytes | None, media_type: str | None, text: str | None
    ) -> AnalysisResult:
        try:
            recognition = self._recognizer.recognize(image, media_type, text)
            if recognition.status is RecognitionStatus.UNCLEAR_IMAGE:
                return AnalysisResult(status=AnalysisStatus.UNCLEAR_IMAGE)
            if recognition.status is RecognitionStatus.NO_FOOD or not recognition.dishes:
                return AnalysisResult(status=AnalysisStatus.NO_FOOD)
            dishes = [self._analyze_dish(guess) for guess in recognition.dishes]
        except RecognizerError as exc:
            return AnalysisResult(status=AnalysisStatus.ERROR, message=str(exc))

        counted = [dish.nutrients for dish in dishes if dish.nutrients is not None]
        return AnalysisResult(status=AnalysisStatus.OK, dishes=dishes, totals=total(counted))

    def _analyze_dish(self, guess: DishGuess) -> AnalyzedDish:
        match = self._matcher.match(guess)
        if match.entry is None:
            self._unmatched.record(guess.name)
            return AnalyzedDish(
                name=guess.name,
                status="unmatched",
                candidates=match.candidates,
                unit=guess.unit,
                quantity=guess.quantity,
                confidence=Confidence.LOW,
            )

        confidence = guess.confidence
        if match.used_chooser:
            confidence = confidence.lowered()
        portion = to_grams(guess.unit, guess.quantity, match.entry, self._household)
        if portion.reduced_confidence:
            confidence = confidence.lowered()
        nutrition = dish_nutrition(match.entry, portion.grams, confidence)
        return AnalyzedDish(
            name=guess.name,
            status=match.status,
            match=Candidate(code=match.entry.code, name=match.entry.name),
            candidates=match.candidates,
            unit=guess.unit,
            quantity=guess.quantity,
            grams=portion.grams,
            grams_low=nutrition.grams_low,
            grams_high=nutrition.grams_high,
            confidence=confidence,
            nutrients=nutrition.nutrients,
        )


def build_engine(settings: Settings) -> Engine:
    from .recognizer import ClaudeRecognizer

    db = FoodDB(settings.food_db_path)
    recognizer = ClaudeRecognizer(model=settings.model)
    matcher = Matcher(
        db,
        recognizer,
        auto_accept_score=settings.auto_accept_score,
        confirm_below_score=settings.confirm_below_score,
    )
    return Engine(
        recognizer,
        matcher,
        load_household_units(settings.household_units_path),
        UnmatchedLog(settings.unmatched_db_path),
    )
