from uuid import UUID
from datetime import date
from app.application.ports.repositories.project_data_repository import IProjectDataRepository
from app.domain.exceptions import DomainValidationException


class ProjectDataUseCase:
    def __init__(self, repository: IProjectDataRepository):
        self.repository = repository

    async def ensure_class_unused(self, project_id, class_id):
        await self.repository.ensure_class_unused(project_id, class_id)

    async def page(self, project_id: UUID, filters: dict) -> dict:
        filters["limit"] = max(1, min(int(filters.get("limit", 48)), 96))
        filters["offset"] = max(0, int(filters.get("offset", 0)))
        for field in ("min_conf", "max_conf"):
            if filters.get(field) is not None and not 0 <= float(filters[field]) <= 1:
                raise DomainValidationException("Уверенность должна быть от 0 до 1")
        for field in ("after", "before"):
            if filters.get(field):
                try: date.fromisoformat(filters[field])
                except ValueError as exc: raise DomainValidationException("Некорректная дата") from exc
        for minimum, maximum in (("min_conf", "max_conf"), ("min_objects", "max_objects"), ("min_area", "max_area")):
            if filters.get(minimum) is not None and filters.get(maximum) is not None and filters[minimum] > filters[maximum]:
                raise DomainValidationException("Нижняя граница не должна превышать верхнюю")
        return await self.repository.page(project_id, filters)

    async def statistics(self, project_id: UUID):
        return await self.repository.statistics(project_id)

    async def cameras(self, project_id: UUID):
        return await self.repository.cameras(project_id)

    async def link_camera(self, project_id: UUID, stream_id: UUID, linked: bool):
        return await self.repository.link_camera(project_id, stream_id, linked)

    async def mutate(self, project_id: UUID, payload: dict):
        if payload.get("action") not in {"tag", "review", "trash", "restore"}:
            raise DomainValidationException("Неизвестное действие")
        return await self.repository.mutate(project_id, payload)
