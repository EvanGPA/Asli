import base64

import anthropic
import httpx
import pytest
from fakes import FakeClient, recorded, text_response

from asli.interfaces import RecognizerError
from asli.models import Candidate, DishGuess, PortionUnit, RecognitionStatus
from asli.recognizer import ClaudeRecognizer


def make(responses):
    client = FakeClient(responses)
    return ClaudeRecognizer(client=client, model="test-model"), client.messages


def test_parses_dishes_and_drops_zero_quantities():
    recognizer, _ = make([recorded("recognize_thali")])
    result = recognizer.recognize(b"img", "image/jpeg", None)
    assert result.status is RecognitionStatus.OK
    assert [d.name for d in result.dishes] == ["chapati", "rajma"]
    assert result.dishes[0].unit is PortionUnit.PIECE
    assert result.dishes[0].quantity == 2


def test_request_sends_image_schema_and_fallback():
    recognizer, messages = make([recorded("recognize_thali")])
    recognizer.recognize(b"img", "image/jpeg", "dal is toor dal")
    call = messages.calls[0]
    assert call["model"] == "test-model"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["fallbacks"] == "default"
    assert call["output_config"]["format"]["type"] == "json_schema"
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[0]["source"]["data"] == base64.standard_b64encode(b"img").decode()
    assert "toor dal" in content[1]["text"]


def test_text_only_request_has_no_image_block():
    recognizer, messages = make([recorded("recognize_thali")])
    recognizer.recognize(None, None, "2 rotis and rajma")
    content = messages.calls[0]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["text"]


def test_no_food_returns_no_dishes():
    recognizer, _ = make([recorded("recognize_no_food")])
    result = recognizer.recognize(b"img", "image/png", None)
    assert result.status is RecognitionStatus.NO_FOOD
    assert result.dishes == []


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refusal_or_cut_off_raises(stop_reason):
    recognizer, _ = make([text_response({"status": "ok", "dishes": []}, stop_reason=stop_reason)])
    with pytest.raises(RecognizerError):
        recognizer.recognize(None, None, "dal")


def test_connection_error_raises_recognizer_error():
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    recognizer, _ = make([error])
    with pytest.raises(RecognizerError):
        recognizer.recognize(None, None, "dal")


def test_invalid_json_raises():
    recognizer, _ = make([text_response("not json")])
    with pytest.raises(RecognizerError):
        recognizer.recognize(None, None, "dal")


def test_wrong_shape_raises():
    # quantity present (so the dish is not dropped) but unit and confidence missing
    recognizer, _ = make([text_response({"status": "ok", "dishes": [{"name": "dal", "quantity": 1}]})])
    with pytest.raises(RecognizerError):
        recognizer.recognize(None, None, "dal")


def test_choose_returns_code_and_limits_answers_to_candidates():
    recognizer, messages = make([text_response({"code": "ASC165"})])
    guess = DishGuess(name="rajma", unit="bowl", quantity=1, confidence="high")
    candidates = [Candidate(code="ASC165", name="Kidney bean curry"), Candidate(code="ASC167", name="Sambar")]
    assert recognizer.choose(guess, candidates) == "ASC165"
    schema = messages.calls[0]["output_config"]["format"]["schema"]
    assert schema["properties"]["code"]["enum"] == ["ASC165", "ASC167", "none"]


def test_choose_none_means_no_match():
    recognizer, _ = make([text_response({"code": "none"})])
    guess = DishGuess(name="mystery", unit="bowl", quantity=1, confidence="low")
    assert recognizer.choose(guess, [Candidate(code="ASC165", name="Kidney bean curry")]) is None


def test_generic_api_error_raises_recognizer_error_without_its_text():
    class OddAPIError(anthropic.APIError):
        pass

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = OddAPIError("secret detail sk-ant-xyz", request, body=None)
    recognizer, _ = make([error])
    with pytest.raises(RecognizerError) as info:
        recognizer.recognize(None, None, "dal")
    assert "secret" not in str(info.value)
    assert "sk-ant" not in str(info.value)
