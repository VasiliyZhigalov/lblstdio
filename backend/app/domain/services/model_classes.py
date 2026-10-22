from dataclasses import replace
from app.domain.exceptions import DomainValidationException


def classes_for_model(classes, model):
    """Preserve class UUIDs while exposing the indices of an imported model head."""
    mapping = (getattr(model, "class_metadata", None) or {}).get("class_mapping")
    if not mapping:
        return classes
    by_id = {str(c.id): c for c in classes}
    if any(class_id not in by_id for class_id in mapping.values()):
        raise DomainValidationException("Словарь модели ссылается на удалённые классы проекта")
    return [replace(by_id[class_id], index_id=int(index)) for index, class_id in mapping.items()]
