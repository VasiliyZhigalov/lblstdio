from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.infrastructure.db.session import create_session_factory, dispose_engine
from app.infrastructure.storage.local_storage import LocalFileStorage
from app.infrastructure.storage.pillow_metadata import PillowMetadataReader
from app.presentation.api.v1.annotations_router import router as annotations_router
from app.presentation.api.v1.images_router import router as images_router
from app.presentation.api.v1.projects_router import router as projects_router
from app.presentation.exception_handlers import register_exception_handlers

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def create_app(
    database_url: str | None = None,
    storage_root: str | Path | None = None,
) -> FastAPI:
    db_url = database_url or "sqlite+aiosqlite:///./app.db"
    files_root = Path(storage_root or "./storage")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine, factory = await create_session_factory(db_url)
        app.state.engine = engine
        app.state.session_factory = factory
        app.state.storage = LocalFileStorage(files_root)
        app.state.metadata_reader = PillowMetadataReader()
        yield
        await dispose_engine(engine)

    app = FastAPI(
        title="Roboflow-Lite API",
        description="Core MVP backend for manual bounding-box labeling and YOLO export.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(images_router, prefix="/api/v1")
    app.include_router(annotations_router, prefix="/api/v1")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return app


app = create_app()
