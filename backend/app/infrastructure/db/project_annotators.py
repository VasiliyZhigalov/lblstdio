from fastapi import HTTPException
from sqlalchemy import delete, select

from app.infrastructure.db.annotation_queue import now
from app.infrastructure.db.tables import AnnotationTaskRow, ProjectAnnotatorRow, ProjectRow, UserRow


async def is_member(session, user_id, project_id) -> bool:
    found = await session.scalar(
        select(ProjectAnnotatorRow.user_id).where(
            ProjectAnnotatorRow.project_id == str(project_id),
            ProjectAnnotatorRow.user_id == str(user_id),
        )
    )
    return found is not None


async def has_active_lease(session, user_id, project_id) -> bool:
    found = await session.scalar(
        select(AnnotationTaskRow.image_id).where(
            AnnotationTaskRow.project_id == str(project_id),
            AnnotationTaskRow.user_id == str(user_id),
            AnnotationTaskRow.state == "WORKING",
            AnnotationTaskRow.lease_until > now(),
        )
    )
    return found is not None


async def project_access(session, user_id, project_id) -> str:
    if await is_member(session, user_id, project_id):
        return "member"
    if await has_active_lease(session, user_id, project_id):
        return "lease"
    return "none"


async def visible_project_ids(session, user_id) -> set[str]:
    assigned = await session.scalars(select(ProjectAnnotatorRow.project_id).where(ProjectAnnotatorRow.user_id == str(user_id)))
    leased = await session.scalars(
        select(AnnotationTaskRow.project_id).where(
            AnnotationTaskRow.user_id == str(user_id),
            AnnotationTaskRow.state == "WORKING",
            AnnotationTaskRow.lease_until > now(),
        )
    )
    return {*(assigned.all()), *(leased.all())}


async def image_permission(session, user_id, image_id) -> tuple[bool, str]:
    from app.infrastructure.db.tables import ImageRow

    image = await session.get(ImageRow, str(image_id))
    if image is None or image.deleted_at is not None:
        return False, "Кадр не входит в очередь разметки"
    access = await project_access(session, user_id, image.project_id)
    if access == "member":
        queued = await session.scalar(
            select(AnnotationTaskRow.image_id).where(
                AnnotationTaskRow.image_id == str(image_id),
                AnnotationTaskRow.state.in_(["QUEUED", "WORKING"]),
            )
        )
        if queued is not None:
            return True, ""
        return False, "Кадр не входит в очередь разметки"
    own = await session.scalar(
        select(AnnotationTaskRow.image_id).where(
            AnnotationTaskRow.image_id == str(image_id),
            AnnotationTaskRow.user_id == str(user_id),
            AnnotationTaskRow.state == "WORKING",
            AnnotationTaskRow.lease_until > now(),
        )
    )
    if own is not None:
        return True, ""
    return False, "Проект вам не назначен"


async def list_annotators(session, project_id) -> list[dict]:
    project = await session.get(ProjectRow, str(project_id))
    if project is None:
        raise HTTPException(404, "Проект не найден")
    rows = (
        await session.execute(
            select(UserRow.id, UserRow.username)
            .join(ProjectAnnotatorRow, ProjectAnnotatorRow.user_id == UserRow.id)
            .where(ProjectAnnotatorRow.project_id == str(project_id))
            .order_by(UserRow.username)
        )
    ).all()
    return [{"id": row.id, "username": row.username} for row in rows]


async def replace_annotators(session, project_id, user_ids) -> list[dict]:
    project = await session.get(ProjectRow, str(project_id))
    if project is None:
        raise HTTPException(404, "Проект не найден")
    ids = list(dict.fromkeys(str(item) for item in user_ids))
    if ids:
        users = (await session.scalars(select(UserRow).where(UserRow.id.in_(ids)))).all()
        found = {user.id: user for user in users}
        if any(item not in found for item in ids):
            raise HTTPException(422, "Неизвестный пользователь")
        if any(user.role != "ANNOTATOR" or not user.is_active for user in found.values()):
            raise HTTPException(422, "Можно закрепить только активных разметчиков")
    await session.execute(delete(ProjectAnnotatorRow).where(ProjectAnnotatorRow.project_id == str(project_id)))
    stamp = now()
    for user_id in ids:
        session.add(ProjectAnnotatorRow(project_id=str(project_id), user_id=user_id, created_at=stamp))
    await session.commit()
    return await list_annotators(session, project_id)
