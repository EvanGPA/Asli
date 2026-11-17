"""Test doubles. Nothing here calls the network."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

FIXTURES = Path(__file__).parent / "fixtures" / "responses"


@dataclass
class FakeBlock:
    type: str
    text: str = ""


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "end_turn"


def text_response(payload: dict | str, stop_reason: str = "end_turn") -> FakeResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return FakeResponse(content=[FakeBlock("thinking"), FakeBlock("text", text)], stop_reason=stop_reason)


def recorded(name: str) -> FakeResponse:
    """Replay a saved AI response from tests/fixtures/responses/<name>.json."""
    return text_response((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeMessages:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    """Mimics anthropic.Anthropic() for client.beta.messages.create(...)."""

    def __init__(self, responses: list):
        self.messages = FakeMessages(responses)
        self.beta = SimpleNamespace(messages=self.messages)


class FakeChooser:
    def __init__(self, answer: str | None):
        self.answer = answer
        self.calls: list[tuple] = []

    def choose(self, guess, candidates):
        self.calls.append((guess, candidates))
        return self.answer


@dataclass
class FakeRecognizer:
    result: object = None
    error: Exception | None = None
    calls: list = field(default_factory=list)

    def recognize(self, image, media_type, text):
        self.calls.append((image, media_type, text))
        if self.error is not None:
            raise self.error
        return self.result
