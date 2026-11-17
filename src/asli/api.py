"""HTTP API for the Asli engine."""

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from python_multipart.multipart import parse_options_header
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import FormParser, MultiPartException, MultiPartParser

from .config import load_settings
from .engine import Engine, build_engine
from .models import AnalysisResult, AnalysisStatus

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Room for the text field and the multipart headers and boundaries around the photo.
MAX_BODY_BYTES = MAX_IMAGE_BYTES + 64 * 1024
# The form is parsed by hand (see _read_form), so describe it for the OpenAPI docs.
_ANALYZE_BODY = {
    "requestBody": {
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "image": {"type": "string", "format": "binary"},
                        "text": {"type": "string"},
                    },
                }
            }
        }
    }
}
UNEXPECTED_ERROR_MESSAGE = "Something went wrong while analysing the meal. Please log it manually."


class _BodyTooLarge(Exception):
    pass


class _InMemoryMultiPartParser(MultiPartParser):
    """Starlette's multipart parser with uploads kept in memory (spec 6: no image on disk).

    Starlette spools each uploaded file into a SpooledTemporaryFile that rolls over to a
    real temporary file past `spool_max_size` (1 MB by default). The request body reaching
    this parser is capped at MAX_BODY_BYTES, so a spool larger than that never rolls over.
    The setting is scoped to this subclass, used only by this app's /analyze route.
    """

    spool_max_size = MAX_BODY_BYTES + 1


async def _capped(stream: AsyncIterator[bytes], limit: int) -> AsyncIterator[bytes]:
    """Pass the body through, stopping as soon as it grows past `limit` bytes."""
    total = 0
    async for chunk in stream:
        total += len(chunk)
        if total > limit:
            raise _BodyTooLarge
        yield chunk


async def _read_form(request: Request) -> FormData:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _BodyTooLarge

    content_type, _ = parse_options_header(request.headers.get("content-type"))
    async with aclosing(_capped(request.stream(), MAX_BODY_BYTES)) as stream:
        if content_type == b"multipart/form-data":
            parser = _InMemoryMultiPartParser(request.headers, stream, max_files=1, max_fields=10)
        elif content_type == b"application/x-www-form-urlencoded":
            parser = FormParser(request.headers, stream, max_fields=10)
        else:
            return FormData()
        try:
            return await parser.parse()
        except MultiPartException as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc


def _error_response(message: str) -> JSONResponse:
    result = AnalysisResult(status=AnalysisStatus.ERROR, message=message)
    return JSONResponse(status_code=503, content=result.model_dump(mode="json"))


def create_app(engine: Engine | None = None) -> FastAPI:
    state: dict[str, Engine | None] = {"engine": engine}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Build the real engine at startup so a missing food database or household units
        # file stops the server from starting instead of failing the first request.
        if state["engine"] is None:
            state["engine"] = build_engine(load_settings())
        yield

    app = FastAPI(title="Asli food analysis engine", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/analyze", openapi_extra=_ANALYZE_BODY)
    async def analyze(request: Request) -> JSONResponse:
        try:
            form = await _read_form(request)
        except _BodyTooLarge:
            raise HTTPException(status_code=413, detail="Photo must be 5 MB or smaller.") from None
        try:
            image = form.get("image")
            text = form.get("text")
            text = text.strip() if isinstance(text, str) and text.strip() else None
            if isinstance(image, str):
                raise HTTPException(status_code=400, detail="The photo must be sent as a file.")
            if image is None and not text:
                raise HTTPException(
                    status_code=400, detail="Send a photo, a text description, or both."
                )

            data: bytes | None = None
            media_type: str | None = None
            if isinstance(image, UploadFile):
                media_type = image.content_type
                if media_type not in ALLOWED_IMAGE_TYPES:
                    raise HTTPException(
                        status_code=415, detail="Photo must be JPEG, PNG, WebP or GIF."
                    )
                data = await image.read()
                if not data:
                    raise HTTPException(status_code=400, detail="The photo is empty.")
                if len(data) > MAX_IMAGE_BYTES:
                    raise HTTPException(status_code=413, detail="Photo must be 5 MB or smaller.")
        finally:
            await form.close()

        try:
            if state["engine"] is None:
                raise RuntimeError("Engine was not built; the application lifespan did not run")
            result = await run_in_threadpool(state["engine"].analyze, data, media_type, text)
        except Exception:
            logger.exception("Unexpected error while analysing a meal")
            return _error_response(UNEXPECTED_ERROR_MESSAGE)
        status_code = 503 if result.status is AnalysisStatus.ERROR else 200
        return JSONResponse(status_code=status_code, content=result.model_dump(mode="json"))

    return app


app = create_app()
