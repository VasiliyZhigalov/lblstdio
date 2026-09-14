from abc import ABC, abstractmethod

from app.application.dto import ProjectBoxesResult, ProjectedBox
from app.domain.value_objects.bounding_box import BoundingBox


class IKeypointMatcher(ABC):
    @abstractmethod
    def project_box(
        self,
        source_image_path: str,
        target_image_path: str,
        source_box: BoundingBox,
        source_width: int,
        source_height: int,
        target_width: int,
        target_height: int,
    ) -> ProjectedBox:
        """Project a normalized source box onto the target image via keypoints."""
        raise NotImplementedError

    @abstractmethod
    def project_boxes(
        self,
        source_image_path: str,
        target_image_path: str,
        source_boxes: list[BoundingBox],
        source_width: int,
        source_height: int,
        target_width: int,
        target_height: int,
    ) -> ProjectBoxesResult:
        """One image-wide transform applied to every box."""
        raise NotImplementedError
