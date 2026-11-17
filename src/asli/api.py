"""HTTP API for the Asli engine."""

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import load_settings
from .engine import Engine, build_engine
from .models import AnalysisStatus

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="Asli food analysis engine")
    state: dict[str, Engine | None] = {"engine": engine}

    def get_engine() -> Engine:
        if state["engine"] is None:
            state["engine"] = build_engine(load_settings())
        return state["engine"]

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/analyze")
    async def analyze(
        image: UploadFile | None = File(None),
        text: str | None = Form(None),
    ) -> JSONResponse:
        text = text.strip() if text else None
        if image is None and not text:
            raise HTTPException(status_code=400, detail="Send a photo, a text description, or both.")

        data: bytes | None = None
        media_type: str | None = None
        if image is not None:
            media_type = image.content_type
            if media_type not in ALLOWED_IMAGE_TYPES:
                raise HTTPException(status_code=415, detail="Photo must be JPEG, PNG, WebP or GIF.")
            data = await image.read()
            if not data:
                raise HTTPException(status_code=400, detail="The photo is empty.")
            if len(data) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="Photo must be 5 MB or smaller.")

        result = await run_in_threadpool(get_engine().analyze, data, media_type, text)
        status_code = 503 if result.status is AnalysisStatus.ERROR else 200
        return JSONResponse(status_code=status_code, content=result.model_dump(mode="json"))

    return app


app = create_app()
