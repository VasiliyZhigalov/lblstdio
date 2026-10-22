from uuid import UUID
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.exceptions import DomainValidationException

COLORS = ["#8B5CF6", "#10B981", "#F59E0B", "#3B82F6", "#EC4899", "#14B8A6"]


def plan_class_mapping(project_id: UUID, names: list[str], requested: dict, classes: list[AnnotationClass]):
    """Allocate new classes without renaming existing classes or changing their indices."""
    if any(not n or len(n) > 255 for n in names) or len(set(names)) != len(names):
        raise DomainValidationException("Имена классов должны быть уникальными и непустыми")
    if set(requested) - {str(i) for i in range(len(names))}:
        raise DomainValidationException("Неизвестный исходный индекс класса")
    by_id = {str(c.id): c for c in classes}
    by_name = {c.name.casefold(): c for c in classes}
    next_index = max((c.index_id for c in classes), default=-1) + 1
    mapping, created = {}, []
    for index, name in enumerate(names):
        selected = requested.get(str(index), "new")
        if selected != "new":
            if selected not in by_id: raise DomainValidationException("Выбран класс из другого проекта")
            cls = by_id[selected]
        else:
            cls = by_name.get(name.casefold())
            if cls is None:
                cls = AnnotationClass.create(project_id, name, COLORS[next_index % len(COLORS)], next_index)
                next_index += 1
                by_name[name.casefold()] = cls
                created.append(cls)
        mapping[str(index)] = str(cls.id)
    if len(set(mapping.values())) != len(mapping):
        raise DomainValidationException("Каждому исходному классу нужен отдельный класс проекта")
    return mapping, created
