import pytest
from fakes import FakeChooser, FakeRecognizer

from asli.engine import Engine
from asli.interfaces import RecognizerError
from asli.matcher import Matcher
from asli.models import (
    AnalysisStatus,
    Confidence,
    DishGuess,
    PortionUnit,
    RecognitionResult,
    RecognitionStatus,
)
from asli.unmatched_log import UnmatchedLog

HOUSEHOLD = {PortionUnit.BOWL: 150.0}


def guess(name, unit, quantity, confidence, *alternatives):
    return DishGuess(
        name=name, alternative_names=list(alternatives), unit=unit, quantity=quantity, confidence=confidence
    )


def make_engine(food_db, tmp_path, recognition=None, error=None, matcher=None):
    recognizer = FakeRecognizer(result=recognition, error=error)
    matcher = matcher or Matcher(food_db, FakeChooser(answer=None))
    log = UnmatchedLog(tmp_path / "unmatched.sqlite")
    return Engine(recognizer, matcher, HOUSEHOLD, log), recognizer, log


def ok(*dishes):
    return RecognitionResult(status=RecognitionStatus.OK, dishes=list(dishes))


def test_thali_gives_dishes_and_totals(food_db, tmp_path):
    recognition = ok(
        guess("roti", "piece", 2, "high"),
        guess("rajma", "bowl", 1, "medium"),
        guess("zzzzqqqq", "bowl", 1, "low"),
    )
    engine, _, log = make_engine(food_db, tmp_path, recognition)
    result = engine.analyze(None, None, "2 roti, rajma")

    assert result.status is AnalysisStatus.OK
    roti, rajma, unknown = result.dishes
    assert roti.status == "matched"
    assert roti.match.code == "ASC096"
    assert roti.grams == pytest.approx(72.0)
    assert roti.confidence is Confidence.HIGH
    assert rajma.grams == pytest.approx(150.0)
    assert rajma.confidence is Confidence.MEDIUM
    assert unknown.status == "unmatched"
    assert unknown.nutrients is None
    # 72 g chapati at 8 g/100 g + 150 g rajma at 6 g/100 g; unmatched dish excluded
    assert result.totals.estimate.protein_g == pytest.approx(5.76 + 9.0)
    assert log.most_common() == [("zzzzqqqq", 1)]


def test_ai_choice_lowers_confidence_and_flags_confirmation(food_db, tmp_path):
    matcher = Matcher(food_db, FakeChooser(answer="ASC165"), auto_accept_score=101, confirm_below_score=101)
    engine, _, _ = make_engine(food_db, tmp_path, ok(guess("kidney beans", "bowl", 1, "high")), matcher=matcher)
    dish = engine.analyze(None, None, "kidney beans").dishes[0]
    assert dish.status == "needs_confirmation"
    assert dish.confidence is Confidence.MEDIUM
    assert dish.candidates[0].code == "ASC165"
    assert dish.nutrients is not None


def test_portion_fallback_lowers_confidence(food_db, tmp_path):
    engine, _, _ = make_engine(food_db, tmp_path, ok(guess("curd dip", "serving", 1, "high")))
    dish = engine.analyze(None, None, "curd dip").dishes[0]
    assert dish.grams == pytest.approx(100.0)
    assert dish.confidence is Confidence.MEDIUM


@pytest.mark.parametrize(
    "recognition_status, expected",
    [
        (RecognitionStatus.NO_FOOD, AnalysisStatus.NO_FOOD),
        (RecognitionStatus.UNCLEAR_IMAGE, AnalysisStatus.UNCLEAR_IMAGE),
    ],
)
def test_no_food_and_unclear_image(food_db, tmp_path, recognition_status, expected):
    engine, _, _ = make_engine(food_db, tmp_path, RecognitionResult(status=recognition_status))
    result = engine.analyze(b"img", "image/jpeg", None)
    assert result.status is expected
    assert result.dishes == []
    assert result.totals is None


def test_ok_with_no_dishes_is_no_food(food_db, tmp_path):
    engine, _, _ = make_engine(food_db, tmp_path, ok())
    assert engine.analyze(None, None, "nothing").status is AnalysisStatus.NO_FOOD


def test_recognizer_error_becomes_error_status(food_db, tmp_path):
    engine, _, _ = make_engine(food_db, tmp_path, error=RecognizerError("Could not reach the AI service"))
    result = engine.analyze(None, None, "dal")
    assert result.status is AnalysisStatus.ERROR
    assert result.message == "Could not reach the AI service"


def test_image_is_never_written_to_disk(food_db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine, recognizer, _ = make_engine(food_db, tmp_path, ok(guess("roti", "piece", 1, "high")))
    engine.analyze(b"\xff\xd8 secret photo bytes", "image/jpeg", None)
    assert recognizer.calls[0][0] == b"\xff\xd8 secret photo bytes"
    files = {p.name for p in tmp_path.rglob("*") if p.is_file()}
    assert files <= {"INDB.xlsx", "aliases.csv", "food.sqlite", "unmatched.sqlite"}
