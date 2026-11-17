"""Interfaces between the engine and the AI recognition step."""

from typing import Protocol

from .models import Candidate, DishGuess, RecognitionResult


class RecognizerError(Exception):
    """The AI service failed or returned something unusable."""


class Recognizer(Protocol):
    def recognize(
        self, image: bytes | None, media_type: str | None, text: str | None
    ) -> RecognitionResult: ...


class CandidateChooser(Protocol):
    def choose(self, guess: DishGuess, candidates: list[Candidate]) -> str | None: ...
