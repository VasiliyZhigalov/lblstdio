from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.application.use_cases.ml.batch_auto_label import AutoLabelJobRunner
from app.application.use_cases.ml.train_model import TrainingJobRunner
from app.infrastructure.db.session import create_session_factory, dispose_engine
from app.infrastructure.ml.device import UltralyticsDeviceResolver
from app.infrastructure.ml.ultralytics_predictor import UltralyticsPredictor
from app.infrastructure.ml.ultralytics_trainer import ProcessUltralyticsTrainer
from app.infrastructure.storage.local_storage import LocalFileStorage
from app.infrastructure.storage.pillow_metadata import PillowMetadataReader
from app.presentation.api.v1.annotations_router import router as annotations_router
from app.presentation.api.v1.dataset_versions_router import router as dataset_versions_router
from app.presentation.api.v1.images_router import router as images_router
from app.presentation.api.v1.matching_router import router as matching_router
from app.presentation.api.v1.projects_router import router as projects_router
from app.presentation.api.v1.stream_router import router as stream_router
from app.presentation.api.v1.training_router import router as training_router
from app.presentation.exception_handlers import register_exception_handlers
from app.settings import load_settings

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def create_app(
    database_url: str | None = None,
    storage_root: str | Path | None = None,
    data_root: str | Path | None = None,
    *,
    training_trainer=None,
    predictor=None,
    stream_runner=None,
) -> FastAPI:
    settings = load_settings(data_root=data_root)
    db_url = database_url or settings.database_url
    files_root = Path(storage_root) if storage_root is not None else settings.storage_root

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.infrastructure.streaming.ingest_consumer import StreamIngestConsumer
        from app.infrastructure.streaming.opencv_stream_runner import OpenCVStreamRunner

        engine, factory = await create_session_factory(db_url)
        app.state.engine = engine
        app.state.session_factory = factory
        app.state.storage = LocalFileStorage(files_root)
        app.state.settings = settings
        app.state.metadata_reader = PillowMetadataReader()
        trainer = training_trainer or ProcessUltralyticsTrainer()
        device_resolver = UltralyticsDeviceResolver()
        app.state.training_runner = TrainingJobRunner(
            factory,
            app.state.storage,
            trainer,
            device_resolver=device_resolver,
            max_concurrent=1,
        )
        app.state.auto_label_runner = AutoLabelJobRunner(
            factory,
            app.state.storage,
            predictor or UltralyticsPredictor(),
            max_concurrent=1,
        )
        app.state.stream_runner = stream_runner or OpenCVStreamRunner()
        app.state.stream_ingest_consumer = StreamIngestConsumer(
            factory, app.state.storage, app.state.stream_runner
        )
        await app.state.training_runner.fail_orphaned_jobs()
        await app.state.auto_label_runner.fail_orphaned_jobs()
        app.state.stream_ingest_consumer.start()
        yield
        await app.state.stream_ingest_consumer.stop()
        app.state.stream_runner.stop_all()
        await dispose_engine(engine)

    app = FastAPI(
        title="LBL_STDIO API",
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
    app.include_router(matching_router, prefix="/api/v1")
    app.include_router(dataset_versions_router, prefix="/api/v1")
    app.include_router(training_router, prefix="/api/v1")
    app.include_router(stream_router, prefix="/api/v1")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "data_root": str(settings.data_root),
            "storage_root": str(Path(files_root).resolve()),
        }

    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return app


app = create_app()
