import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, update
from app.domain.entities.annotation import Annotation
from app.domain.entities.image import Image
from app.domain.entities.image_label import ImageLabel
from app.domain.enums import ImageSourceType, SplitType, ImageStatus
from app.domain.value_objects.bounding_box import BoundingBox
from app.domain.exceptions import DomainValidationException as Invalid
from app.domain.services.import_classes import plan_class_mapping
from app.infrastructure.db.tables import DataImportRow as Job, ClassRow, ImageRow, ImageDataRow, ProjectRow
from app.infrastructure.db.mappers import image_to_row, annotation_to_row, label_to_row, row_to_class, class_to_row
from app.infrastructure.db.repositories.project_data_repository import SqliteProjectDataRepository
from app.infrastructure.storage.dataset_manifest import inspect_dataset, inspect_model
from app.application.use_cases.ml.manage_model_version import UploadModelVersionUseCase
from app.infrastructure.db.repositories.project_repository import SqliteProjectRepository
from app.infrastructure.db.repositories.model_version_repository import SqliteModelVersionRepository
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork



def public_job(row):
    return {"id": row.id, "name": row.name, "kind": row.kind, "status": row.status, "created_at": row.created_at.isoformat(), "processed": row.processed, "total": row.total, "error": row.error, "summary": row.summary}


class DataImportManager:
    """Durable import state with background workers holding their own DB sessions."""
    def __init__(self, factory, storage):
        self.factory, self.storage = factory, storage
        self.root = Path(storage.get_absolute_path("_imports"))
        self.root.mkdir(exist_ok=True)
        self.tasks = {}
        self.cancelled = set()
        self.lock = asyncio.Lock()

    async def recover(self):
        async with self.factory() as session:
            await session.execute(update(Job).where(Job.status.in_(["RUNNING", "QUEUED"])).values(status="FAILED", error="Сервер был перезапущен. Уже импортированные изображения сохранены; можно отменить импорт."))
            await session.commit()

    async def close(self):
        self.cancelled.update(self.tasks)
        if self.tasks: await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def prepare(self, project_id, kind, uploads, root):
        async with self.factory() as session:
            await SqliteProjectDataRepository(session).require_project(project_id)
            project = await session.get(ProjectRow, str(project_id))
            task = project.task_type
        try:
            if kind == "model":
                if len(uploads) != 1 or not uploads[0][0].lower().endswith(".pt"): raise Invalid("Выберите один файл .pt")
                manifest = await asyncio.to_thread(inspect_model, uploads[0][1], task)
            else:
                manifest = await asyncio.to_thread(inspect_dataset, root, uploads, task, kind)
        except Invalid: raise
        except Exception as exc: raise Invalid(f"Не удалось прочитать импорт: {exc}") from exc
        job_id = root.name
        await asyncio.to_thread((root / "manifest.json").write_text, json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        summary = {"format": manifest["format"], "names": manifest["names"], "class_count": manifest.get("class_count"), "images": len(manifest["records"]), "objects": sum(len(r["boxes"]) for r in manifest["records"]), "backgrounds": sum(bool(r["background"]) for r in manifest["records"])}
        async with self.factory() as session:
            row = Job(id=job_id, project_id=str(project_id), kind=kind, name=uploads[0][0] if len(uploads) == 1 else f"{len(uploads)} файлов", created_at=datetime.now(timezone.utc), summary=summary, total=len(manifest["records"]) or 1)
            session.add(row)
            await session.commit()
            return public_job(row)

    async def list(self, project_id):
        async with self.factory() as session:
            rows = (await session.scalars(select(Job).where(Job.project_id == str(project_id)).order_by(Job.created_at.desc()).limit(100))).all()
            return [public_job(r) for r in rows]

    async def owned(self, session, project_id, job_id):
        row = await session.get(Job, str(job_id))
        if row is None or row.project_id != str(project_id): raise Invalid("Импорт не найден")
        return row

    async def start(self, project_id, job_id, payload):
        async with self.lock:
            async with self.factory() as session:
                job = await self.owned(session, project_id, job_id)
                if job.status != "PREVIEW": raise Invalid("Этот импорт уже запускался")
                manifest = json.loads((self.root / str(job_id) / "manifest.json").read_text(encoding="utf-8"))
                names = manifest["names"]
                supplied = payload.get("names")
                if supplied:
                    if len(supplied) != len(names) and names: raise Invalid("Количество классов не совпадает с моделью")
                    names = [str(n).strip() for n in supplied]
                    manifest["names"] = names
                if job.kind == "model" and not names: raise Invalid("Укажите названия классов модели")
                if job.kind == "model" and manifest.get("class_count") and len(names) != manifest["class_count"]:
                    raise Invalid(f"У модели {manifest['class_count']} выходов. Укажите столько же названий классов.")
                classes = list((await session.scalars(select(ClassRow).where(ClassRow.project_id == str(project_id)))).all())
                mapping, created = plan_class_mapping(UUID(str(project_id)), names, payload.get("mapping") or {}, [row_to_class(c) for c in classes])
                for cls in created: session.add(class_to_row(cls))
                # Classes are committed with the import reservation; no existing name is changed.
                manifest["mapping"] = mapping
                (self.root / str(job_id) / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                job.status = "QUEUED"
                await session.commit()
                result = public_job(job)
            task = asyncio.create_task(self.run(str(project_id), str(job_id), manifest))
            self.tasks[str(job_id)] = task
            task.add_done_callback(lambda _: self.tasks.pop(str(job_id), None))
            return result

    async def run(self, project_id, job_id, manifest):
        saved = []
        try:
            async with self.factory() as session:
                job = await session.get(Job, job_id)
                job.status = "RUNNING"
                await session.commit()
                if job.kind == "model":
                    uc = UploadModelVersionUseCase(SqliteProjectRepository(session), SqliteModelVersionRepository(session), self.storage, SqlAlchemyUnitOfWork(session))
                    model = await uc.execute(UUID(project_id), filename=job.name, source_path=Path(manifest["model_path"]), activate=False, class_metadata={"class_names": manifest["names"], "class_mapping": manifest["mapping"]})
                    job.summary = {**job.summary, "model_id": str(model.id)}
                    job.processed = 1
                else:
                    records = manifest["records"]
                    for offset in range(0, len(records), 50):
                        if job_id in self.cancelled:
                            job.status = "CANCELLED"
                            await session.commit()
                            return
                        for r in records[offset:offset+50]:
                            path = await self.storage.save_from_path(f"projects/{project_id}/images", Path(r["name"]).name, Path(r["path"]))
                            saved.append(path)
                            image = Image.create(project_id=UUID(project_id), file_path=path, file_name=Path(r["name"]).name, width=r["width"], height=r["height"], source_type=ImageSourceType.DATASET_IMPORT if job.kind == "dataset" else ImageSourceType.MANUAL_UPLOAD, split=SplitType(r["split"]))
                            annotations = [Annotation.create_manual(image.id, UUID(manifest["mapping"][str(b[0])]), BoundingBox(*b[1:])) for b in r["boxes"]]
                            if r["label"] is not None: image.status = ImageStatus.VERIFIED
                            elif r["background"]: image.mark_as_background()
                            elif annotations: image.recalculate_status(annotations)
                            session.add(image_to_row(image))
                            await session.flush()
                            for a in annotations: session.add(annotation_to_row(a))
                            if r["label"] is not None: session.add(label_to_row(ImageLabel.create_manual(image.id, UUID(manifest["mapping"][str(r["label"])]))))
                            session.add(ImageDataRow(image_id=str(image.id), import_id=job_id, tags=[]))
                        job.processed = min(offset+50, len(records))
                        await session.commit()
                        saved.clear()
                job.status = "COMPLETED"
                await session.commit()
            # Preview/source files can be large; completed jobs keep only their DB report.
            await asyncio.to_thread(shutil.rmtree, self.root / job_id)
        except Exception as exc:
            for path in saved: await self.storage.delete(path)
            async with self.factory() as session:
                job = await session.get(Job, job_id)
                if job:
                    job.status, job.error = "FAILED", str(exc)[:2000]
                    await session.commit()
        finally:
            self.cancelled.discard(job_id)

    async def cancel_or_rollback(self, project_id, job_id, rollback=False):
        async with self.factory() as session:
            job = await self.owned(session, project_id, job_id)
            if job.status in {"RUNNING", "QUEUED"}:
                if rollback: raise Invalid("Сначала остановите импорт и дождитесь завершения")
                self.cancelled.add(str(job_id))
                return {"status": "CANCELLING"}
            if rollback:
                if job.kind not in {"images", "dataset"}: raise Invalid("Отмена доступна только для импорта изображений")
                ids = select(ImageDataRow.image_id).where(ImageDataRow.import_id == str(job_id))
                from app.infrastructure.db.tables import AnnotationTaskRow
                active = select(AnnotationTaskRow.image_id).where(AnnotationTaskRow.state == "WORKING", AnnotationTaskRow.lease_until > datetime.now(timezone.utc))
                await session.execute(update(ImageRow).where(ImageRow.project_id == str(project_id), ImageRow.id.in_(ids), ImageRow.id.not_in(active)).values(deleted_at=datetime.now(timezone.utc)))
                job.status = "ROLLED_BACK"
            elif job.status == "PREVIEW":
                job.status = "CANCELLED"
                await asyncio.to_thread(shutil.rmtree, self.root / str(job_id), True)
            await session.commit()
            return public_job(job)

    async def analyze(self, project_id):
        async with self.factory() as session:
            await SqliteProjectDataRepository(session).require_project(project_id)
            active = await session.scalar(select(Job).where(Job.project_id == str(project_id), Job.kind == "quality", Job.status.in_(["RUNNING", "QUEUED"])))
            if active: return {"message": "Анализ уже выполняется. Прогресс — в истории импорта."}
            job = Job(id=str(uuid4()), project_id=str(project_id), kind="quality", name="Анализ качества изображений", created_at=datetime.now(timezone.utc), status="QUEUED", summary={"format": "Качество / pHash"})
            session.add(job)
            await session.commit()
            task = asyncio.create_task(self.run_analysis(str(project_id), job.id))
            self.tasks[job.id] = task
            task.add_done_callback(lambda _: self.tasks.pop(job.id, None))
        return {"message": "Анализ запущен. Прогресс — в разделе «Импорт и модели»."}

    async def run_analysis(self, project_id, job_id):
        import cv2
        import numpy as np
        from PIL import Image as PILImage
        from app.infrastructure.storage.pillow_metadata import PillowMetadataReader
        def measure(path):
            with PILImage.open(path) as source:
                gray = source.convert("L")
                gray.thumbnail((640, 640))
                pixels = np.asarray(gray)
                brightness = float(pixels.mean())
                sharpness = float(cv2.Laplacian(pixels, cv2.CV_64F).var())
            phash = PillowMetadataReader().perceptual_hash(Path(path).read_bytes())
            return brightness, sharpness, f"{phash:016x}"
        try:
            async with self.factory() as session:
                job = await session.get(Job, job_id)
                job.status = "RUNNING"
                ids = list((await session.scalars(select(ImageRow.id).where(ImageRow.project_id == project_id, ImageRow.deleted_at.is_(None)))).all())
                job.total = len(ids)
                await session.commit()
                errors = []
                for i, image_id in enumerate(ids):
                    if job_id in self.cancelled:
                        job.status = "CANCELLED"
                        await session.commit()
                        return
                    row = await session.get(ImageRow, image_id)
                    if row is None: continue
                    try:
                        brightness, sharpness, phash = await asyncio.to_thread(measure, self.storage.get_absolute_path(row.file_path))
                        meta = await session.get(ImageDataRow, image_id)
                        if meta is None: meta = ImageDataRow(image_id=image_id, tags=[]); session.add(meta)
                        meta.brightness, meta.sharpness, row.phash = brightness, sharpness, phash
                    except (OSError, ValueError) as exc: errors.append(f"{row.file_name}: {exc}")
                    job.processed = i+1
                    if i % 25 == 0: await session.commit()
                job.status = "COMPLETED"
                job.summary = {**job.summary, "errors": errors[:100]}
                job.error = f"Не прочитано файлов: {len(errors)}" if errors else None
                await session.commit()
        except Exception as exc:
            async with self.factory() as session:
                job = await session.get(Job, job_id)
                job.status, job.error = "FAILED", str(exc)[:2000]
                await session.commit()
        finally: self.cancelled.discard(job_id)
