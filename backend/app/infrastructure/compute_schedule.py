"""Persistent platform schedule and exclusive training admission."""
import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from dataclasses import replace
from uuid import UUID
from sqlalchemy import select
from app.infrastructure.db.tables import ComputePolicyRow, TrainingJobRow
from app.application.ports.services.stream_runner import StreamStatus

DEFAULTS = {"collection_start": "07:00", "collection_end": "18:00", "training_start": "18:00", "training_end": "07:00"}

def in_window(start, end, at=None):
    at = at or datetime.now().astimezone()
    minute = at.hour * 60 + at.minute
    a, b = (int(x[:2])*60+int(x[3:]) for x in (start,end))
    return a <= minute < b if a < b else minute >= a or minute < b


class ScheduledStreamRunner:
    def __init__(self, runner, policy):
        self.runner, self.policy = runner, policy
        self.launches = {}
        self.lock = threading.RLock()
        self.training = False

    def __getattr__(self, name): return getattr(self.runner, name)
    def allowed(self): return not self.training and in_window(self.policy["collection_start"],self.policy["collection_end"])
    def start(self, stream, weights_abs_path, *, allowed_class_indices=None):
        with self.lock:
            self.launches[stream.id] = [stream,weights_abs_path,allowed_class_indices]
            if self.allowed(): self.runner.start(stream,weights_abs_path,allowed_class_indices=allowed_class_indices)
    def wait_until_ready(self, stream_id, timeout=30):
        if stream_id in self.launches and not self.allowed(): return self.get_status(stream_id)
        return self.runner.wait_until_ready(stream_id,timeout=timeout)
    def get_status(self, stream_id):
        status = replace(self.runner.get_status(stream_id))
        if stream_id in self.launches and not self.allowed():
            status.is_running = False
            status.state = "waiting_gpu" if self.training else "scheduled"
        return status
    def stop(self, stream_id):
        with self.lock:
            self.launches.pop(stream_id,None)
            self.runner.stop(stream_id)
    def stop_project(self, project_id):
        for sid, launch in list(self.launches.items()):
            if launch[0].project_id == project_id: self.stop(sid)
    def stop_all(self):
        with self.lock:
            self.launches.clear();self.runner.stop_all()
    def update_triggers(self, stream_id, config, *, allowed_class_indices=None):
        with self.lock:
            if stream_id in self.launches:
                self.launches[stream_id][0].config = config
                self.launches[stream_id][2] = allowed_class_indices
            self.runner.update_triggers(stream_id,config,allowed_class_indices=allowed_class_indices)
    def reconcile(self):
        with self.lock:
            for sid,(stream,weights,indices) in list(self.launches.items()):
                status=self.runner.get_status(sid)
                if not self.allowed():
                    if status.state not in {"stopped", "idle"}: self.runner.stop(sid)
                elif status.state in {"stopped","idle"}:
                    self.runner.start(stream,weights,allowed_class_indices=indices)


class ComputeSchedule:
    def __init__(self, factory, runner):
        self.factory=factory
        self.settings=dict(DEFAULTS)
        self.streams=ScheduledStreamRunner(runner,self.settings)
        self.gpu=asyncio.Lock()
        self.task=None
        self.error=None
        self.predictors=[]

    def release_inference_resources(self):
        import gc
        import sys
        for predictor in self.predictors:
            release=getattr(predictor,"release",None)
            if release:release()
        gc.collect()
        torch=sys.modules.get("torch")
        if torch is not None and torch.cuda.is_available():torch.cuda.empty_cache()

    async def load(self):
        async with self.factory() as session:
            row=await session.get(ComputePolicyRow,1)
            if row: self.settings.update(row.settings)
    async def save(self, values):
        async with self.factory() as session:
            row=await session.get(ComputePolicyRow,1)
            if row: row.settings=dict(values)
            else: session.add(ComputePolicyRow(id=1,settings=dict(values)))
            await session.commit()
        self.settings.update(values)
        await asyncio.to_thread(self.streams.reconcile)
    def start(self): self.task=asyncio.create_task(self.loop())
    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
    async def loop(self):
        while True:
            try:
                await asyncio.to_thread(self.streams.reconcile)
                await self.enqueue_completed_auto_labels()
                self.error=None
            except Exception as exc: self.error=str(exc)
            await asyncio.sleep(10)
    async def enqueue_completed_auto_labels(self):
        from sqlalchemy import update, or_, exists
        from app.infrastructure.db.tables import AutoLabelJobRow, ImageRow, AnnotationRow, ImageLabelRow, AnnotationTaskRow
        from app.infrastructure.db.annotation_queue import SqliteAnnotationQueue
        async with self.factory() as session:
            jobs=list(await session.scalars(select(AutoLabelJobRow).where(AutoLabelJobRow.status=="COMPLETED",AutoLabelJobRow.enqueue_for_annotation==1)))
        for job in jobs:
            async with self.factory() as session:
                ids=list(await session.scalars(select(ImageRow.id).where(ImageRow.id.in_(job.image_ids_json),ImageRow.deleted_at.is_(None),ImageRow.id.not_in(select(AnnotationTaskRow.image_id).where(AnnotationTaskRow.state=="DONE")),or_(exists().where(AnnotationRow.image_id==ImageRow.id),exists().where(ImageLabelRow.image_id==ImageRow.id)))))
                await session.execute(update(AutoLabelJobRow).where(AutoLabelJobRow.id==job.id).values(enqueue_for_annotation=0))
                if ids: await SqliteAnnotationQueue(session).enqueue(UUID(job.project_id),{},ids,False)
                else: await session.commit()

    async def restore_sources(self, storage):
        import logging
        from app.infrastructure.db.tables import StreamSourceRow
        from app.infrastructure.db.repositories.stream_source_repository import SqliteStreamSourceRepository
        from app.infrastructure.db.repositories.model_version_repository import SqliteModelVersionRepository
        from app.infrastructure.db.repositories.class_repository import SqliteClassRepository
        from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
        from app.application.use_cases.streaming.control_stream import StartStreamUseCase
        async with self.factory() as session:
            ids=list(await session.scalars(select(StreamSourceRow.id).where(StreamSourceRow.is_active==1)))
        for sid in ids:
            try:
                async with self.factory() as session:
                    uc=StartStreamUseCase(SqliteStreamSourceRepository(session),SqliteModelVersionRepository(session),SqliteClassRepository(session),storage,self.streams,SqlAlchemyUnitOfWork(session))
                    await uc.execute(UUID(sid))
            except Exception:
                logging.getLogger(__name__).exception("Cannot restore scheduled source %s",sid)

    @asynccontextmanager
    async def inference_slot(self, job_id):
        async with self.gpu:
            self.streams.training=True
            try:
                await asyncio.to_thread(self.streams.reconcile)
                yield
            finally:
                try: await asyncio.to_thread(self.release_inference_resources)
                finally:
                    self.streams.training=False
                    await asyncio.to_thread(self.streams.reconcile)

    async def eligible_training(self, job_id):
        from sqlalchemy import or_
        async with self.factory() as session:
            job=await session.get(TrainingJobRow,str(job_id))
            if not job or job.status!="QUEUED": return None
            night=in_window(self.settings["training_start"],self.settings["training_end"])
            q=select(TrainingJobRow.id).where(TrainingJobRow.status=="QUEUED",or_(TrainingJobRow.not_before.is_(None),TrainingJobRow.not_before<=datetime.now(timezone.utc)))
            if not night:q=q.where(TrainingJobRow.schedule_mode=="now")
            first=await session.scalar(q.order_by(TrainingJobRow.created_at,TrainingJobRow.id).limit(1))
            return first==str(job_id)

    @asynccontextmanager
    async def training_slot(self, job_id):
        while True:
            ready=await self.eligible_training(job_id)
            if ready is None:
                yield
                return
            if ready:
                await self.gpu.acquire()
                try:
                    # A long inference job may have occupied GPU across the window boundary.
                    if await self.eligible_training(job_id):
                        self.streams.training=True
                        try:
                            await asyncio.to_thread(self.streams.reconcile)
                            await asyncio.to_thread(self.release_inference_resources)
                            yield
                        finally:
                            self.streams.training=False
                            await asyncio.to_thread(self.streams.reconcile)
                        return
                finally:self.gpu.release()
            await asyncio.sleep(2)
