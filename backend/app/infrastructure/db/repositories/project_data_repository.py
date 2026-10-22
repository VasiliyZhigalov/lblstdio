from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, func, or_, update, literal
from sqlalchemy.dialects.sqlite import insert
from app.infrastructure.db.tables import (
    ImageRow as I, AnnotationRow as A, ImageLabelRow as L, ImageDataRow as D,
    ClassRow, ProjectRow, ProjectCameraRow, StreamSourceRow, DatasetItemRow, ModelVersionRow,
)
from app.domain.exceptions import DomainValidationException


class SqliteProjectDataRepository:
    def __init__(self, session):
        self.session = session

    async def require_project(self, project_id):
        if await self.session.get(ProjectRow, str(project_id)) is None:
            raise DomainValidationException("Проект не найден")

    async def ensure_class_unused(self, project_id, class_id):
        row = await self.session.get(ClassRow, str(class_id))
        if row is None or row.project_id != str(project_id): raise DomainValidationException("Класс не найден")
        for table in (A, L):
            if await self.session.scalar(select(func.count()).select_from(table).where(table.class_id == str(class_id))):
                raise DomainValidationException("Класс используется в разметке, включая корзину. Сначала переназначьте объекты.")
        if await self.session.scalar(select(func.count()).select_from(ModelVersionRow).where(ModelVersionRow.project_id == str(project_id))):
            raise DomainValidationException("В проекте есть модели. Удаление изменит индексы классов; сначала удалите связанные модели или сохраните словарь без удаления.")

    def query(self, project_id, f):
        count = select(func.count(A.id)).where(A.image_id == I.id).correlate(I).scalar_subquery()
        confidence = func.coalesce(
            select(func.min(A.confidence)).where(A.image_id == I.id, A.source == "MODEL_PREDICTION").correlate(I).scalar_subquery(),
            select(L.confidence).where(L.image_id == I.id, L.source == "MODEL_PREDICTION").correlate(I).scalar_subquery())
        q = select(I).where(I.project_id == str(project_id))
        q = q.where(I.deleted_at.is_not(None) if f.get("trash") else I.deleted_at.is_(None))
        for field in ("status", "split", "source_type", "stream_source_id"):
            if f.get(field):
                q = q.where(getattr(I, field).in_(str(f[field]).split(",")))
        if f.get("q"):
            term = str(f["q"]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q = q.where(I.file_name.ilike(f"%{term}%", escape="\\"))
        if f.get("class_id"):
            ids = str(f["class_id"]).split(",")
            q = q.where(or_(select(A.id).where(A.image_id == I.id, A.class_id.in_(ids)).exists(), select(L.id).where(L.image_id == I.id, L.class_id.in_(ids)).exists()))
        if f.get("annotation_source"):
            q = q.where(or_(select(A.id).where(A.image_id == I.id, A.source == f["annotation_source"]).exists(), select(L.id).where(L.image_id == I.id, L.source == f["annotation_source"]).exists()))
        if f.get("min_area") is not None or f.get("max_area") is not None:
            boxes = select(A.id).where(A.image_id == I.id)
            if f.get("min_area") is not None: boxes = boxes.where(A.width * A.height >= f["min_area"])
            if f.get("max_area") is not None: boxes = boxes.where(A.width * A.height <= f["max_area"])
            q = q.where(boxes.exists())
        if f.get("orientation") == "landscape": q = q.where(I.width > I.height)
        if f.get("orientation") == "portrait": q = q.where(I.width < I.height)
        if f.get("orientation") == "square": q = q.where(I.width == I.height)
        if f.get("format"):
            suffix = f["format"]
            q = q.where(or_(I.file_name.ilike("%.jpg"), I.file_name.ilike("%.jpeg")) if suffix == "jpg" else I.file_name.ilike(f"%.{suffix}"))
        for key, expr in (("min_objects", count), ("min_width", I.width), ("min_height", I.height), ("min_conf", confidence)):
            if f.get(key) is not None and f[key] != "": q = q.where(expr >= float(f[key]))
        for key, expr in (("max_objects", count), ("max_conf", confidence)):
            if f.get(key) is not None and f[key] != "": q = q.where(expr <= float(f[key]))
        if f.get("background") is not None: q = q.where(I.is_background == int(bool(f["background"])))
        if f.get("after"): q = q.where(I.created_at >= datetime.fromisoformat(f["after"]))
        if f.get("before"): q = q.where(I.created_at < datetime.fromisoformat(f["before"]))
        if f.get("tag"):
            q = q.where(select(D.image_id).where(D.image_id == I.id, func.json_each(D.tags).table_valued("value").c.value == f["tag"]).exists())
        if f.get("version_id"):
            q = q.where(I.id.in_(select(DatasetItemRow.image_id).where(DatasetItemRow.dataset_version_id == f["version_id"])))
        if f.get("duplicates"):
            q = q.where(I.phash.in_(select(I.phash).where(I.project_id == str(project_id), I.deleted_at.is_(None), I.phash.is_not(None)).group_by(I.phash).having(func.count() > 1)))
        if f.get("quality") == "dark":
            q = q.where(select(D.image_id).where(D.image_id == I.id, D.brightness < 50).exists())
        if f.get("quality") == "blur":
            q = q.where(select(D.image_id).where(D.image_id == I.id, D.sharpness < 70).exists())
        order = {"oldest": I.created_at.asc(), "name": I.file_name.asc(), "uncertainty": confidence.asc(), "objects": count.desc()}.get(f.get("sort"), I.created_at.desc())
        return q, order

    async def page(self, project_id: UUID, filters: dict):
        await self.require_project(project_id)
        q, order = self.query(project_id, filters)
        total = await self.session.scalar(select(func.count()).select_from(q.subquery()))
        rows = list((await self.session.scalars(q.order_by(order, I.id).offset(filters["offset"]).limit(filters["limit"]))).all())
        ids = [r.id for r in rows]
        boxes = (await self.session.scalars(select(A).where(A.image_id.in_(ids)))).all() if ids else []
        labels = {r.image_id: r for r in (await self.session.scalars(select(L).where(L.image_id.in_(ids)))).all()} if ids else {}
        meta = {r.image_id: r for r in (await self.session.scalars(select(D).where(D.image_id.in_(ids)))).all()} if ids else {}
        grouped = {}
        for b in boxes: grouped.setdefault(b.image_id, []).append({k: getattr(b, k) for k in ("id", "class_id", "x_center", "y_center", "width", "height", "source", "confidence", "verification_status")})
        result = []
        for r in rows:
            item = {k: getattr(r, k) for k in ("id", "file_name", "width", "height", "status", "split", "source_type", "stream_source_id", "is_background")}
            item["created_at"] = r.created_at.isoformat()
            item["annotations"] = grouped.get(r.id, [])
            label = labels.get(r.id)
            item["label"] = {k: getattr(label, k) for k in ("class_id", "source", "confidence", "verification_status")} if label else None
            item["tags"] = meta[r.id].tags if r.id in meta else []
            conf = [b["confidence"] for b in item["annotations"] if b["source"] == "MODEL_PREDICTION"]
            if label and label.source == "MODEL_PREDICTION": conf.append(label.confidence)
            item["confidence"] = min(conf) if conf else None
            result.append(item)
        return {"items": result, "total": total, "limit": filters["limit"], "offset": filters["offset"]}

    async def statistics(self, project_id):
        await self.require_project(project_id)
        where = (I.project_id == str(project_id), I.deleted_at.is_(None))
        async def groups(column):
            return [{"name": name, "count": n} for name, n in (await self.session.execute(select(column, func.count()).where(*where).group_by(column))).all()]
        classes = (await self.session.execute(select(A.class_id, func.count(), func.count(func.distinct(A.image_id))).join(I, I.id == A.image_id).where(*where).group_by(A.class_id))).all()
        labels = (await self.session.execute(select(L.class_id, func.count()).join(I, I.id == L.image_id).where(*where).group_by(L.class_id))).all()
        class_counts = {c: {"id": c, "objects": n, "images": images} for c, n, images in classes}
        for c, n in labels: class_counts[c] = {"id": c, "objects": n, "images": n}
        duplicates = select(I.phash, func.count().label("n"), func.count(func.distinct(I.split)).label("splits")).where(*where, I.phash.is_not(None)).group_by(I.phash).having(func.count() > 1).subquery()
        analyzed = await self.session.scalar(select(func.count()).select_from(D).join(I, I.id == D.image_id).where(*where, D.brightness.is_not(None)))
        return {"total": await self.session.scalar(select(func.count()).select_from(I).where(*where)), "analyzed": analyzed, "statuses": await groups(I.status), "splits": await groups(I.split), "sources": await groups(I.stream_source_id), "days": sorted(await groups(func.date(I.created_at)), key=lambda d: d["name"] or ""), "classes": list(class_counts.values()), "duplicates": await self.session.scalar(select(func.coalesce(func.sum(duplicates.c.n - 1), 0))), "leakage_groups": await self.session.scalar(select(func.count()).select_from(duplicates).where(duplicates.c.splits > 1)), "trash": await self.session.scalar(select(func.count()).select_from(I).where(I.project_id == str(project_id), I.deleted_at.is_not(None)))}

    async def cameras(self, project_id):
        await self.require_project(project_id)
        links = select(ProjectCameraRow.stream_id).where(ProjectCameraRow.project_id == str(project_id))
        rows = (await self.session.scalars(select(StreamSourceRow).where(or_(StreamSourceRow.project_id == str(project_id), StreamSourceRow.id.in_(links))))).all()
        return [{"id": r.id, "name": r.name, "project_id": r.project_id, "source_type": r.source_type, "is_active": r.is_active, "owned": r.project_id == str(project_id)} for r in rows]

    async def link_camera(self, project_id, stream_id, linked):
        await self.require_project(project_id)
        source = await self.session.get(StreamSourceRow, str(stream_id))
        if source is None: raise DomainValidationException("Камера не найдена")
        if source.project_id == str(project_id) and not linked: raise DomainValidationException("Это камера проекта. Управляйте ею в Центре сбора.")
        key = {"project_id": str(project_id), "stream_id": str(stream_id)}
        row = await self.session.get(ProjectCameraRow, key)
        if linked and row is None: self.session.add(ProjectCameraRow(**key))
        if not linked and row: await self.session.delete(row)
        await self.session.commit()

    async def mutate(self, project_id, payload):
        await self.require_project(project_id)
        f = dict(payload.get("filters") or {})
        q, _ = self.query(project_id, f)
        if not payload.get("all_matching"):
            ids = list(payload.get("ids") or [])
            if len(ids) > 5000: raise DomainValidationException("Не более 5000 изображений за операцию")
            q = q.where(I.id.in_(ids))
        action = payload["action"]
        targets = q.with_only_columns(I.id)
        count = await self.session.scalar(select(func.count()).select_from(targets.subquery()))
        if action == "tag":
            tag = str(payload.get("tag", "")).strip()[:64]
            if not tag: raise DomainValidationException("Введите тег")
            # Both statements act on the same bounded SQL selection; no per-image queries.
            await self.session.execute(insert(D).from_select(["image_id", "tags"], targets.add_columns(literal("[]"))).on_conflict_do_nothing(index_elements=["image_id"]))
            existing = func.json_each(D.tags).table_valued("value")
            await self.session.execute(update(D).where(D.image_id.in_(targets), ~select(existing.c.value).where(existing.c.value == tag).exists()).values(tags=func.json_insert(D.tags, "$[#]", tag)))
        elif action in ("trash", "restore"):
            await self.session.execute(update(I).where(I.id.in_(targets)).values(deleted_at=datetime.now(timezone.utc) if action == "trash" else None))
        elif action == "review":
            await self.session.execute(update(I).where(I.id.in_(targets)).values(status="REQUIRES_RECHECK"))
        else: raise DomainValidationException("Неизвестное действие")
        await self.session.commit()
        return {"updated": count}
