import pytest
from fastapi.testclient import TestClient

from asli.api import MAX_IMAGE_BYTES, create_app
from asli.models import AnalysisResult, AnalysisStatus


class FakeEngine:
    def __init__(self, result: AnalysisResult):
        self.result = result
        self.calls = []

    def analyze(self, image, media_type, text):
        self.calls.append((image, media_type, text))
        return self.result


def client_with(status=AnalysisStatus.OK, message=None):
    engine = FakeEngine(AnalysisResult(status=status, message=message))
    return TestClient(create_app(engine)), engine


def test_health():
    client, _ = client_with()
    assert client.get("/health").json() == {"status": "ok"}


def test_neither_image_nor_text_is_400():
    client, engine = client_with()
    assert client.post("/analyze").status_code == 400
    assert client.post("/analyze", data={"text": "   "}).status_code == 400
    assert engine.calls == []


def test_text_only():
    client, engine = client_with()
    response = client.post("/analyze", data={"text": "2 rotis and dal"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert engine.calls == [(None, None, "2 rotis and dal")]


def test_image_upload_passes_bytes_and_type():
    client, engine = client_with()
    response = client.post("/analyze", files={"image": ("meal.jpg", b"jpeg-bytes", "image/jpeg")})
    assert response.status_code == 200
    assert engine.calls == [(b"jpeg-bytes", "image/jpeg", None)]


def test_unsupported_image_type_is_415():
    client, _ = client_with()
    response = client.post("/analyze", files={"image": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_empty_image_is_400():
    client, _ = client_with()
    response = client.post("/analyze", files={"image": ("meal.jpg", b"", "image/jpeg")})
    assert response.status_code == 400


def test_image_too_large_is_413():
    client, _ = client_with()
    big = b"x" * (MAX_IMAGE_BYTES + 1)
    response = client.post("/analyze", files={"image": ("meal.jpg", big, "image/jpeg")})
    assert response.status_code == 413


@pytest.mark.parametrize("status", [AnalysisStatus.NO_FOOD, AnalysisStatus.UNCLEAR_IMAGE])
def test_no_food_and_unclear_photo_are_200(status):
    client, _ = client_with(status=status)
    response = client.post("/analyze", files={"image": ("meal.jpg", b"jpeg-bytes", "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["status"] == status.value


def test_engine_error_is_503_with_message():
    client, _ = client_with(status=AnalysisStatus.ERROR, message="Could not reach the AI service")
    response = client.post("/analyze", data={"text": "dal"})
    assert response.status_code == 503
    assert response.json() == {
        "status": "error", "message": "Could not reach the AI service", "dishes": [], "totals": None,
    }
