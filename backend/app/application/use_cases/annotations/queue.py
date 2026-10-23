from app.application.ports.repositories.annotation_queue import IAnnotationQueue
from app.domain.exceptions import DomainValidationException


class AnnotationQueue:
    def __init__(self, repository: IAnnotationQueue):
        self.repository = repository

    async def list(self, project_id, owner, state="all", offset=0, limit=48):
        return await self.repository.list(project_id, owner, state, max(0, offset), max(1, min(96, limit)))

    async def claim(self, project_id, owner, image_id=None):
        return await self.repository.claim(project_id, owner, image_id)

    async def action(self, project_id, image_id, owner, action, revision, reason=""):
        if action not in {"heartbeat", "release", "finish", "skip", "clear", "trash", "background"}:
            raise DomainValidationException("Неизвестное действие очереди")
        return await self.repository.action(project_id, image_id, owner, action, revision, reason.strip()[:2000])
