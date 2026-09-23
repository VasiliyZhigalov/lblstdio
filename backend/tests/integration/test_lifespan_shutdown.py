"""Shutdown must finish active runner tasks before the engine is disposed."""

import asyncio
from uuid import uuid4

import pytest

from app.application.use_cases.ml.batch_auto_label import AutoLabelJobRunner
from app.application.use_cases.ml.train_model import TrainingJobRunner
from app.infrastructure.db.session import dispose_engine
from app.infrastructure.streaming.opencv_stream_runner import FakeStreamRunner
from app.main import create_app


@pytest.mark.asyncio
async def test_lifespan_finishes_active_jobs_before_dispose(tmp_path, monkeypatch) -> None:
    order: list[str] = []
    started = asyncio.Event()
    running = {"n": 0}
    jobs_at_dispose = {"n": -1}

    async def _hang(self, job_id) -> None:
        running["n"] += 1
        if running["n"] >= 2:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            order.append("job")

    async def _track_dispose(engine) -> None:
        jobs_at_dispose["n"] = order.count("job")
        order.append("dispose")
        await dispose_engine(engine)

    monkeypatch.setattr(TrainingJobRunner, "_run", _hang)
    monkeypatch.setattr(AutoLabelJobRunner, "_run", _hang)
    monkeypatch.setattr("app.main.dispose_engine", _track_dispose)

    app = create_app(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}",
        storage_root=tmp_path / "files",
        stream_runner=FakeStreamRunner(),
    )
    try:
        async with app.router.lifespan_context(app):
            app.state.training_runner.schedule(uuid4())
            app.state.auto_label_runner.schedule(uuid4())

            async def _audit_job() -> None:
                running["n"] += 1
                if running["n"] >= 3:
                    started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    order.append("job")

            audit_task = asyncio.create_task(_audit_job())
            app.state.audit_annotations_runner._running.add(audit_task)
            audit_task.add_done_callback(app.state.audit_annotations_runner._running.discard)
            await asyncio.wait_for(started.wait(), timeout=5)
    finally:
        for runner in (
            getattr(app.state, "training_runner", None),
            getattr(app.state, "auto_label_runner", None),
            getattr(app.state, "audit_annotations_runner", None),
        ):
            if runner is None:
                continue
            pending = set(getattr(runner, "_tasks", ()) or ()) | set(
                getattr(runner, "_running", ()) or ()
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    assert jobs_at_dispose["n"] == 3
