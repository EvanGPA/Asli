from fakes import FakeChooser

from asli.matcher import Matcher
from asli.models import DishGuess


def guess(name: str, *alternatives: str) -> DishGuess:
    return DishGuess(
        name=name, alternative_names=list(alternatives), unit="bowl", quantity=1, confidence="high"
    )


def test_exact_alias_matches_without_asking_the_ai(food_db):
    chooser = FakeChooser(answer="ASC096")
    result = Matcher(food_db, chooser).match(guess("roti"))
    assert result.status == "matched"
    assert result.entry.code == "ASC096"
    assert result.used_chooser is False
    assert chooser.calls == []


def test_alternative_name_can_produce_the_match(food_db):
    result = Matcher(food_db, FakeChooser(answer=None)).match(guess("lal lobia", "rajma"))
    assert result.entry.code == "ASC165"
    assert result.status == "matched"


def test_weak_match_asks_the_ai_with_candidates(food_db):
    chooser = FakeChooser(answer="ASC165")
    matcher = Matcher(food_db, chooser, auto_accept_score=101, confirm_below_score=0)
    result = matcher.match(guess("kidney beans"))
    assert result.status == "matched"
    assert result.entry.code == "ASC165"
    assert result.used_chooser is True
    offered = [c.code for c in chooser.calls[0][1]]
    assert "ASC165" in offered
    assert len(offered) <= 5


def test_low_scoring_ai_choice_needs_confirmation(food_db):
    matcher = Matcher(food_db, FakeChooser(answer="ASC165"), auto_accept_score=101, confirm_below_score=101)
    result = matcher.match(guess("kidney beans"))
    assert result.status == "needs_confirmation"
    assert result.entry.code == "ASC165"
    assert result.candidates[0].code == "ASC165"
    assert 1 <= len(result.candidates) <= 3


def test_ai_says_none_gives_unmatched_with_candidates(food_db):
    matcher = Matcher(food_db, FakeChooser(answer=None), auto_accept_score=101)
    result = matcher.match(guess("kidney beans"))
    assert result.status == "unmatched"
    assert result.entry is None
    assert len(result.candidates) <= 3


def test_ai_choice_outside_candidates_is_rejected(food_db):
    matcher = Matcher(food_db, FakeChooser(answer="NOT_OFFERED"), auto_accept_score=101)
    assert matcher.match(guess("kidney beans")).status == "unmatched"


def test_no_search_hits_is_unmatched_without_ai_call(food_db):
    chooser = FakeChooser(answer="ASC096")
    result = Matcher(food_db, chooser).match(guess("zzzzqqqq"))
    assert result.status == "unmatched"
    assert chooser.calls == []
