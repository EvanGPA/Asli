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


def test_two_megabyte_photo_is_never_written_to_disk(monkeypatch):
    import tempfile

    def no_disk(*args, **kwargs):
        raise AssertionError("an uploaded photo must not be written to disk")

    for name in ("TemporaryFile", "NamedTemporaryFile", "mkstemp", "_mkstemp_inner"):
        monkeypatch.setattr(tempfile, name, no_disk)

    client, engine = client_with()
    photo = bytes(range(256)) * (2 * 1024 * 1024 // 256)
    response = client.post("/analyze", files={"image": ("meal.jpg", photo, "image/jpeg")})
    assert response.status_code == 200
    assert engine.calls == [(photo, "image/jpeg", None)]


def test_photo_at_the_cap_is_accepted():
    client, engine = client_with()
    photo = b"x" * MAX_IMAGE_BYTES
    response = client.post(
        "/analyze", files={"image": ("meal.jpg", photo, "image/jpeg")}, data={"text": "dal"}
    )
    assert response.status_code == 200
    assert engine.calls[0][0] == photo


def test_declared_content_length_over_the_cap_is_413_before_reading():
    client, engine = client_with()
    response = client.post(
        "/analyze",
        content=b"",
        headers={
            "content-type": "multipart/form-data; boundary=abc",
            "content-length": str(50 * 1024 * 1024),
        },
    )
    assert response.status_code == 413
    assert engine.calls == []


def test_streamed_body_over_the_cap_is_413_without_reading_it_all():
    """A chunked upload with no Content-Length is cut off once it passes the cap."""
    import asyncio

    engine = FakeEngine(AnalysisResult(status=AnalysisStatus.OK))
    app = create_app(engine)
    head = b'--abc\r\nContent-Disposition: form-data; name="image"; filename="m.jpg"\r\n'
    head += b"Content-Type: image/jpeg\r\n\r\n"
    chunks = [head] + [b"x" * (256 * 1024)] * 200  # 50 MB if fully read
    received = []
    sent = []

    async def receive():
        if len(received) < len(chunks):
            received.append(len(chunks[len(received)]))
            return {"type": "http.request", "body": chunks[len(received) - 1], "more_body": True}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/analyze", "raw_path": b"/analyze", "query_string": b"",
        "root_path": "", "headers": [(b"content-type", b"multipart/form-data; boundary=abc")],
        "client": ("test", 1), "server": ("test", 80),
    }
    asyncio.run(app(scope, receive, send))
    assert sent[0]["status"] == 413
    assert engine.calls == []
    assert sum(received) <= MAX_IMAGE_BYTES + 1024 * 1024


class RaisingEngine:
    def analyze(self, image, media_type, text):
        raise RuntimeError("database is locked: /secret/path")


def test_unexpected_engine_exception_is_503_error_payload(caplog):
    client = TestClient(create_app(RaisingEngine()), raise_server_exceptions=False)
    with caplog.at_level("ERROR"):
        response = client.post("/analyze", data={"text": "dal"})
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["dishes"] == [] and body["totals"] is None
    assert body["message"] and "secret" not in body["message"]
    assert "RuntimeError" in caplog.text
    assert any(record.exc_info for record in caplog.records)


def test_lifespan_builds_the_engine_when_none_is_injected(monkeypatch):
    import asli.api as api

    built = []
    fake = FakeEngine(AnalysisResult(status=AnalysisStatus.OK))
    monkeypatch.setattr(api, "load_settings", lambda: "settings")
    monkeypatch.setattr(api, "build_engine", lambda settings: built.append(settings) or fake)

    app = create_app()
    assert built == []
    with TestClient(app) as client:
        assert built == ["settings"]
        assert client.post("/analyze", data={"text": "dal"}).status_code == 200
    assert built == ["settings"]
    assert fake.calls == [(None, None, "dal")]


def test_lifespan_failure_stops_startup(monkeypatch):
    import asli.api as api

    def missing(settings):
        raise FileNotFoundError("no food db")

    monkeypatch.setattr(api, "load_settings", lambda: "settings")
    monkeypatch.setattr(api, "build_engine", missing)
    with pytest.raises(FileNotFoundError):
        with TestClient(create_app()):
            pass


def test_injected_engine_is_not_rebuilt_at_startup(monkeypatch):
    import asli.api as api

    def boom(*args):
        raise AssertionError("must not build")

    monkeypatch.setattr(api, "load_settings", boom)
    monkeypatch.setattr(api, "build_engine", boom)
    engine = FakeEngine(AnalysisResult(status=AnalysisStatus.OK))
    with TestClient(create_app(engine)) as client:
        assert client.post("/analyze", data={"text": "dal"}).status_code == 200
