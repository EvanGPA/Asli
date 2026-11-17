"""Match a recognized dish to a databank entry (spec 4.3)."""

from dataclasses import dataclass

from .food_db import FoodDB
from .interfaces import CandidateChooser
from .models import Candidate, DishGuess, DishStatus, FoodEntry


@dataclass(frozen=True)
class MatchResult:
    status: DishStatus
    entry: FoodEntry | None
    candidates: list[Candidate]
    used_chooser: bool


class Matcher:
    def __init__(
        self,
        db: FoodDB,
        chooser: CandidateChooser,
        auto_accept_score: float = 90.0,
        confirm_below_score: float = 60.0,
        candidate_count: int = 5,
    ):
        self._db = db
        self._chooser = chooser
        self._auto_accept = auto_accept_score
        self._confirm_below = confirm_below_score
        self._candidate_count = candidate_count

    def match(self, guess: DishGuess) -> MatchResult:
        hits = self._db.search_many(
            [guess.name, *guess.alternative_names], limit=self._candidate_count
        )
        if not hits:
            return MatchResult("unmatched", None, [], used_chooser=False)

        top_entry, top_score = hits[0]
        if top_score >= self._auto_accept:
            return MatchResult("matched", top_entry, [], used_chooser=False)

        candidates = [Candidate(code=e.code, name=e.name) for e, _ in hits]
        scores = {e.code: score for e, score in hits}
        chosen = self._chooser.choose(guess, candidates)
        if chosen is None or chosen not in scores:
            return MatchResult("unmatched", None, candidates[:3], used_chooser=True)

        entry = self._db.get(chosen)
        if scores[chosen] < self._confirm_below:
            others = [c for c in candidates if c.code != chosen][:2]
            return MatchResult(
                "needs_confirmation",
                entry,
                [Candidate(code=entry.code, name=entry.name), *others],
                used_chooser=True,
            )
        return MatchResult("matched", entry, [], used_chooser=True)
