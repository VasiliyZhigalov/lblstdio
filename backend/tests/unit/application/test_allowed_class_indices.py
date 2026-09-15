from uuid import uuid4

from app.application.use_cases.streaming.control_stream import allowed_class_indices_for
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.enums import TripwireDirection
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig


def test_allowed_class_indices_none_means_all():
    project_id = uuid4()
    classes = [AnnotationClass.create(project_id, "car", "#FFFFFF", 0)]
    cfg = StreamTriggerConfig(tripwire_classes=())
    assert allowed_class_indices_for(cfg, classes) is None


def test_allowed_class_indices_maps_uuids():
    project_id = uuid4()
    car = AnnotationClass.create(project_id, "car", "#FFFFFF", 0)
    person = AnnotationClass.create(project_id, "person", "#00FF00", 1)
    cfg = StreamTriggerConfig(
        tripwire_classes=(car.id,),
        tripwire_direction=TripwireDirection.ANY,
    )
    assert allowed_class_indices_for(cfg, [car, person]) == frozenset({0})
