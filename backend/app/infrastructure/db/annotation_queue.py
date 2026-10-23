import hashlib
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select, update, delete, func, or_, and_, literal
from sqlalchemy.dialects.sqlite import insert
from app.infrastructure.db.tables import AnnotationTaskRow as T, ImageRow as I, AnnotationRow as A, ImageLabelRow as L, ProjectRow
from app.infrastructure.db.repositories.project_data_repository import SqliteProjectDataRepository
from app.domain.exceptions import DomainValidationException

LEASE_SECONDS = 180


class QueueConflict(DomainValidationException):
    pass


def now(): return datetime.now(timezone.utc)


def session_owner(value):
    try: token = str(UUID(value or ""))
    except (ValueError, TypeError, AttributeError): raise QueueConflict("Откройте вкладку заново: отсутствует сессия разметки")
    return hashlib.sha256(token.encode()).hexdigest()


def public(row, owner):
    until = row.lease_until
    if until and until.tzinfo is None: until = until.replace(tzinfo=timezone.utc)
    active = row.state == "WORKING" and until and until > now()
    return {"image_id": row.image_id, "state": row.state if row.state != "WORKING" or active else "QUEUED", "mine": bool(active and row.owner == owner), "lease_until": until.isoformat() if active else None, "revision": row.revision, "reason": row.reason, "updated_at": row.updated_at.isoformat()}


async def require_write(session, image_id, owner, revision):
    task = await session.get(T, str(image_id))
    if task is None: return None
    if owner is None or revision is None:
        raise QueueConflict("Сначала получите кадр в работу из очереди")
    # The conditional write reserves SQLite's writer lock for the entire mutation.
    result = await session.execute(update(T).execution_options(synchronize_session=False).where(T.image_id == str(image_id), T.state == "WORKING", T.owner == owner, T.lease_until > now(), T.revision == revision).values(revision=T.revision + 1, updated_at=now()).returning(T.revision))
    updated = result.scalar_one_or_none()
    if updated is None: raise QueueConflict("Кадр занят, блокировка истекла или версия изменилась. Перезагрузите кадр; локальный черновик сохранён.")
    session.info.setdefault("annotation_writes", set()).add(str(image_id))
    return updated


async def protect_background_write(session, image_id):
    if str(image_id) in session.info.get("annotation_writes", set()): return
    if await session.get(T, str(image_id)) is not None:
        raise QueueConflict("Кадр находится в очереди разметки. Фоновая перезапись недоступна; завершите работу с очередью.")


class SqliteAnnotationQueue:
    def __init__(self, session): self.session = session

    async def list(self, project_id, owner, state, offset, limit):
        await SqliteProjectDataRepository(self.session).require_project(project_id)
        box_count = select(func.count(A.id)).where(A.image_id == I.id).correlate(I).scalar_subquery()
        base = select(T, I, box_count).join(I, I.id == T.image_id).where(T.project_id == str(project_id), I.deleted_at.is_(None))
        base = base.where(T.state.in_(["QUEUED", "WORKING"]))
        timestamp = now()
        available = or_(T.state == "QUEUED", and_(T.state == "WORKING", T.lease_until <= timestamp))
        if state == "available": base = base.where(available)
        elif state == "mine": base = base.where(T.state == "WORKING", T.owner == owner, T.lease_until > timestamp)
        elif state in {"DONE", "ISSUE"}: base = base.where(T.state == state)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        rows = (await self.session.execute(base.order_by(T.updated_at.desc(), T.image_id).offset(offset).limit(limit))).all()
        stats = dict((await self.session.execute(select(T.state, func.count()).join(I, I.id == T.image_id).where(T.project_id == str(project_id), I.deleted_at.is_(None)).group_by(T.state))).all())
        expired = await self.session.scalar(select(func.count()).select_from(T).join(I, I.id == T.image_id).where(T.project_id == str(project_id), I.deleted_at.is_(None), T.state == "WORKING", T.lease_until <= timestamp))
        stats["QUEUED"] = stats.get("QUEUED", 0) + expired
        stats["WORKING"] = stats.get("WORKING", 0) - expired
        return {"items": [{**public(t, owner), "image": {**{k: getattr(i, k) for k in ("id", "file_name", "width", "height", "status", "split", "source_type", "is_background")}, "annotation_count": count}} for t, i, count in rows], "total": total, "offset": offset, "limit": limit, "counts": stats}

    async def enqueue(self, project_id, filters, ids, all_matching):
        await SqliteProjectDataRepository(self.session).require_project(project_id)
        q, _ = SqliteProjectDataRepository(self.session).query(project_id, filters)
        q = q.where(I.deleted_at.is_(None))
        if not all_matching: q = q.where(I.id.in_(ids))
        targets = q.with_only_columns(I.id)
        stamp = now()
        # Re-enqueue is explicit; live leases are preserved even for the caller.
        statement = insert(T).from_select(["image_id", "project_id", "state", "revision", "created_at", "updated_at"], targets.add_columns(literal(str(project_id)), literal("QUEUED"), literal(0), literal(stamp), literal(stamp)))
        statement = statement.on_conflict_do_update(index_elements=["image_id"], set_={"state": "QUEUED", "owner": None, "lease_until": None, "reason": None, "revision": T.revision+1, "updated_at": stamp}, where=or_(T.state != "WORKING", T.lease_until <= stamp))
        result = await self.session.execute(statement)
        await self.session.execute(update(I).where(I.id.in_(targets), I.id.in_(select(T.image_id).where(T.state == "QUEUED"))).values(status="IN_PROGRESS"))
        await self.session.commit()
        return {"updated": result.rowcount}

    async def claim(self, project_id, owner, image_id=None):
        await SqliteProjectDataRepository(self.session).require_project(project_id)
        stamp = now()
        if image_id is not None:
            image = await self.session.get(I, str(image_id))
            if not image or image.project_id != str(project_id) or image.deleted_at: raise DomainValidationException("Кадр не найден в проекте")
            existing = await self.session.get(T, str(image_id))
            if (existing and existing.state == "DONE") or (not existing and image.status in {"VERIFIED", "AUTO_VERIFIED"}):
                raise QueueConflict("Кадр уже завершён и не входит в очередь разметки")
            # Opening an unfinished image explicitly takes it into the queue.
            await self.session.execute(insert(T).values(image_id=str(image_id), project_id=str(project_id), state="QUEUED", revision=0, created_at=stamp, updated_at=stamp).on_conflict_do_nothing(index_elements=["image_id"]))
            task = await self.session.get(T, str(image_id))
            target = str(image_id)
        else:
            # Prefer the caller's current frame; repeated clicks cannot reserve a batch.
            target = select(T.image_id).join(I, I.id == T.image_id).where(T.project_id == str(project_id), I.deleted_at.is_(None), or_(T.state == "QUEUED", and_(T.state == "WORKING", or_(T.owner == owner, T.lease_until <= stamp)))).order_by((T.owner == owner).desc(), T.updated_at, T.image_id).limit(1).scalar_subquery()
        result = await self.session.execute(update(T).execution_options(synchronize_session=False).where(T.image_id == target, or_(T.state == "QUEUED", and_(T.state == "WORKING", or_(T.owner == owner, T.lease_until <= stamp)))).values(state="WORKING", owner=owner, lease_until=stamp+timedelta(seconds=LEASE_SECONDS), updated_at=stamp).returning(T.image_id))
        acquired = result.scalar_one_or_none()
        if acquired is None:
            if image_id is None:
                await self.session.commit()
                return {"image_id": None}
            raise QueueConflict("Кадр уже взял другой разметчик. Выберите следующий свободный.")
        target = acquired
        await self.session.execute(update(I).where(I.id == target).values(status="IN_PROGRESS"))
        await self.session.execute(update(T).execution_options(synchronize_session=False).where(T.project_id == str(project_id), T.image_id != target, T.owner == owner, T.state == "WORKING").values(state="QUEUED", owner=None, lease_until=None, updated_at=stamp))
        await self.session.commit()
        task = await self.session.get(T, target, populate_existing=True)
        return {**public(task, owner), "readonly": False}

    async def action(self, project_id, image_id, owner, action, revision, reason):
        task = await self.session.get(T, str(image_id))
        if task is None or task.project_id != str(project_id): raise DomainValidationException("Задание не найдено")
        if action == "heartbeat":
            result = await self.session.execute(update(T).execution_options(synchronize_session=False).where(T.image_id == str(image_id), T.state == "WORKING", T.owner == owner, T.lease_until > now()).values(lease_until=now()+timedelta(seconds=LEASE_SECONDS)).returning(T.image_id))
            if result.scalar_one_or_none() is None: raise QueueConflict("Право редактирования истекло. Черновик сохранён локально.")
        else:
            await require_write(self.session, image_id, owner, revision)
            if action == "background":
                project = await self.session.get(ProjectRow, str(project_id))
                if project.task_type == "CLASSIFICATION": raise DomainValidationException("Фон доступен только для детекции объектов")
                await self.session.execute(delete(A).where(A.image_id == str(image_id)))
                await self.session.execute(update(I).where(I.id == str(image_id)).values(is_background=True))
                action = "finish"
            if action in {"clear", "trash"}:
                image = await self.session.get(I, str(image_id))
                if image.deleted_at: raise QueueConflict("Изображение перемещено в корзину")
                if action == "clear":
                    await self.session.execute(delete(A).where(A.image_id == str(image_id)))
                    await self.session.execute(delete(L).where(L.image_id == str(image_id)))
                    await self.session.execute(update(I).where(I.id == str(image_id)).values(status="UNANNOTATED", is_background=False))
                else:
                    await self.session.execute(update(I).where(I.id == str(image_id)).values(deleted_at=now()))
                await self.session.execute(delete(T).where(T.image_id == str(image_id)))
                await self.session.commit()
                return {"image_id": str(image_id), "state": "REMOVED", "mine": False, "revision": revision + 1}
            if action == "finish":
                image = await self.session.get(I, str(image_id))
                if image.deleted_at: raise QueueConflict("Изображение перемещено в корзину")
                project = await self.session.get(ProjectRow, str(project_id))
                if project.task_type == "CLASSIFICATION":
                    label = await self.session.scalar(select(L).where(L.image_id == str(image_id)))
                    if not label: raise DomainValidationException("Назначьте класс изображения")
                    label.verification_status = "VERIFIED"
                else:
                    boxes = list((await self.session.scalars(select(A).where(A.image_id == str(image_id)))).all())
                    for box in boxes:
                        box.verification_status = "VERIFIED"
                    if not boxes and not image.is_background: raise DomainValidationException("Нарисуйте объекты или отметьте отсутствие целевых объектов")
                await self.session.execute(update(I).where(I.id == str(image_id)).values(status="VERIFIED"))
            await self.session.execute(update(T).execution_options(synchronize_session=False).where(T.image_id == str(image_id)).values(state={"finish":"DONE", "skip":"QUEUED", "release":"QUEUED"}[action], owner=None, lease_until=None, reason=None, updated_at=now()))
        await self.session.commit()
        return public(await self.session.get(T, str(image_id), populate_existing=True), owner)
