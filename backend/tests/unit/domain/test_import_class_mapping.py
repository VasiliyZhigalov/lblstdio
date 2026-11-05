from uuid import uuid4
from types import SimpleNamespace
import pytest
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.exceptions import DomainValidationException
from app.domain.services.import_classes import plan_class_mapping
from app.domain.services.model_classes import classes_for_model


def test_imported_model_indices_keep_project_class_identity():
    pid = uuid4()
    car = AnnotationClass.create(pid, "Car", "#123456", 0)
    person = AnnotationClass.create(pid, "Person", "#654321", 3)
    mapping, created = plan_class_mapping(pid, ["Person source", "Car source", "Bicycle"], {"0": str(person.id), "1": str(car.id)}, [car, person])
    assert len(created) == 1 and created[0].index_id == 4
    model = SimpleNamespace(class_metadata={"class_mapping": mapping})
    resolved = classes_for_model([car, person, *created], model)
    assert [(c.index_id, c.id) for c in resolved] == [(0, person.id), (1, car.id), (2, created[0].id)]
    assert car.index_id == 0 and person.index_id == 3


def test_import_class_mapping_rejects_foreign_and_duplicate_targets():
    pid = uuid4()
    car = AnnotationClass.create(pid, "Car", "#123456", 0)
    with pytest.raises(DomainValidationException): plan_class_mapping(pid, ["Person"], {"0": str(uuid4())}, [car])
    with pytest.raises(DomainValidationException): plan_class_mapping(pid, ["Car", "CAR"], {}, [car])
    with pytest.raises(DomainValidationException): classes_for_model([], SimpleNamespace(class_metadata={"class_mapping": {"0": str(car.id)}}))
