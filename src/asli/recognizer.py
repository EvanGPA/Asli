"""Dish recognition and candidate choice using the Claude API."""

import base64
import json

import anthropic

from .interfaces import RecognizerError
from .models import (
    Candidate,
    Confidence,
    DishGuess,
    PortionUnit,
    RecognitionResult,
    RecognitionStatus,
)

DEFAULT_MODEL = "claude-opus-5-5"

RECOGNIZE_SYSTEM = """You identify food in meal photos and meal descriptions for an Indian nutrition tracker.

Report each distinct dish or food item that is being eaten. Do not estimate nutrients.

For each dish give:
- name: the name most Indians would use, for example "rajma", "bhindi sabzi", "chapati".
- alternative_names: other common names, including the English name, for example ["kidney bean curry"].
- unit and quantity: how much is present, using only these units: serving, bowl (a katori), plate, piece (for countable items such as roti, idli, dosa, samosa), cup, glass, tablespoon, teaspoon. Quantity may be fractional, for example 0.5 plate.
- confidence: "high" if the dish and amount are clear, "medium" if either is uncertain, "low" if you are mostly guessing.

Set status to "no_food" if no food or drink is being eaten, "unclear_image" if the photo is too blurry, dark or cropped to tell, and "ok" otherwise. With "no_food" or "unclear_image", return an empty dishes list.

If a text description comes with a photo, use it for what the photo cannot show, such as which dal it is. If the text and the photo disagree about what is present, trust the text."""

CHOOSE_SYSTEM = """You match a dish to an entry in the Indian Nutrient Databank. You are given the dish as it was described and a list of databank entries with their codes. Answer with the code of the entry that is the same dish, or "none" if no entry is the same dish. A similar dish with different main ingredients is not the same dish."""

RECOGNITION_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": [s.value for s in RecognitionStatus]},
        "dishes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "alternative_names": {"type": "array", "items": {"type": "string"}},
                    "unit": {"type": "string", "enum": [u.value for u in PortionUnit]},
                    "quantity": {"type": "number"},
                    "confidence": {"type": "string", "enum": [c.value for c in Confidence]},
                },
                "required": ["name", "alternative_names", "unit", "quantity", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "dishes"],
    "additionalProperties": False,
}


class ClaudeRecognizer:
    def __init__(self, client=None, model: str = DEFAULT_MODEL):
        self._client = client or anthropic.Anthropic(max_retries=1, timeout=60.0)
        self._model = model

    def recognize(
        self, image: bytes | None, media_type: str | None, text: str | None
    ) -> RecognitionResult:
        content: list[dict] = []
        if image is not None:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.standard_b64encode(image).decode("utf-8"),
                    },
                }
            )
        prompt = f"Meal description: {text}" if text else "Identify the food in this photo."
        content.append({"type": "text", "text": prompt})

        data = self._call(RECOGNIZE_SYSTEM, content, RECOGNITION_SCHEMA, effort="medium")
        try:
            status = RecognitionStatus(data["status"])
            dishes = [
                DishGuess(**dish)
                for dish in data.get("dishes", [])
                if isinstance(dish, dict) and float(dish.get("quantity", 0) or 0) > 0
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise RecognizerError("AI response did not match the expected format") from exc
        if status is not RecognitionStatus.OK:
            dishes = []
        return RecognitionResult(status=status, dishes=dishes)

    def choose(self, guess: DishGuess, candidates: list[Candidate]) -> str | None:
        codes = [c.code for c in candidates]
        schema = {
            "type": "object",
            "properties": {"code": {"type": "string", "enum": [*codes, "none"]}},
            "required": ["code"],
            "additionalProperties": False,
        }
        lines = "\n".join(f"{c.code}: {c.name}" for c in candidates)
        also = ", ".join(guess.alternative_names) or "none"
        prompt = f"Dish: {guess.name}\nAlso called: {also}\n\nDatabank entries:\n{lines}"
        data = self._call(CHOOSE_SYSTEM, [{"type": "text", "text": prompt}], schema, effort="low")
        code = data.get("code")
        return code if code in codes else None

    def _call(self, system: str, content: list[dict], schema: dict, effort: str) -> dict:
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=16000,
                system=system,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.APIStatusError as exc:
            raise RecognizerError(f"AI service returned an error ({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise RecognizerError("Could not reach the AI service") from exc

        if response.stop_reason == "refusal":
            raise RecognizerError("The AI service declined this request")
        if response.stop_reason == "max_tokens":
            raise RecognizerError("The AI response was cut off")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise RecognizerError("The AI response had no text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RecognizerError("The AI response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise RecognizerError("The AI response was not a JSON object")
        return data
