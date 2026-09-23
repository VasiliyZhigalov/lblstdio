from uuid import UUID, uuid4

import pytest

from app.application.dto import UploadedFile
from app.application.use_cases.images.upload_images import UploadImagesUseCase
from app.domain.entities.annotation import Annotation
from app.domain.entities.annotation_class import AnnotationClass
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import ImageStatus, ProjectTaskType, SplitType, VerificationStatus
from app.domain.exceptions import (
    DomainValidationException,
    ResourceNotFoundException,
    TaskTypeMismatchException,
)


class _FakeStorage:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, bytes]] = []
        self.deleted: list[str] = []

    async def save(self, relative_dir: str, filename: str, data: bytes) -> str:
        path = f"{relative_dir}/{filename}"
        self.saved.append((relative_dir, filename, data))
        return path

    async def delete(self, relative_path: str) -> None:
        self.deleted.append(relative_path)


class _FakeMetadata:
    def __init__(self, size: tuple[int, int] = (320, 240)) -> None:
        self.size = size
        self.seen: list[bytes] = []

    def read_size(self, data: bytes) -> tuple[int, int]:
        self.seen.append(data)
        return self.size


class _FakeProjects:
    def __init__(self, project: Project | None) -> None:
        self.project = project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        if self.project and self.project.id == project_id:
            return self.project
        return None


class _FakeImages:
    def __init__(self) -> None:
        self.added: list[Image] = []
        self.updated: list[Image] = []

    async def add_many(self, images: list[Image]) -> None:
        self.added.extend(images)

    async def update(self, image: Image) -> None:
        self.updated.append(image)


class _FakeAnnotations:
    def __init__(self) -> None:
        self.replaced: dict[UUID, list[Annotation]] = {}

    async def replace_for_image(self, image_id: UUID, annotations) -> None:
        self.replaced[image_id] = list(annotations)


class _FakeClasses:
    def __init__(self, classes: list[AnnotationClass] | None = None) -> None:
        self.classes = list(classes or [])

    async def list_by_project(self, project_id: UUID) -> list[AnnotationClass]:
        return [item for item in self.classes if item.project_id == project_id]

    async def add(self, annotation_class: AnnotationClass) -> None:
        self.classes.append(annotation_class)


class _FakeUow:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def _use_case(
    project: Project | None = None,
    *,
    classes: list[AnnotationClass] | None = None,
):
    project = project or Project.create("Demo")
    images = _FakeImages()
    metadata = _FakeMetadata()
    uow = _FakeUow()
    annotations = _FakeAnnotations()
    class_repo = _FakeClasses(classes)
    use_case = UploadImagesUseCase(
        projects=_FakeProjects(project),
        images=images,
        storage=_FakeStorage(),
        metadata=metadata,
        uow=uow,
        annotations=annotations,
        classes=class_repo,
    )
    return use_case, images, metadata, uow, project, annotations, class_repo


class TestUploadImagesUseCase:
    @pytest.mark.asyncio
    async def test_assigns_train_stub_split_and_reads_dimensions(self) -> None:
        use_case, images, metadata, uow, project, *_ = _use_case()
        files = [
            UploadedFile(filename=f"img_{index}.png", content=b"payload-%d" % index)
            for index in range(10)
        ]

        result = await use_case.execute(project.id, files)

        assert all(item.split == SplitType.TRAIN for item in result)
        assert all(item.status == ImageStatus.UNANNOTATED for item in result)
        assert all(item.width == 320 and item.height == 240 for item in result)
        assert metadata.seen == [item.content for item in files]
        assert images.added == result
        assert uow.committed is True

    @pytest.mark.asyncio
    async def test_imports_yolo_labels_as_verified_manual(self) -> None:
        use_case, images, _, uow, project, annotations, class_repo = _use_case()
        result = await use_case.execute(
            project.id,
            [
                UploadedFile(filename="train/images/a.jpg", content=b"img-a"),
                UploadedFile(
                    filename="train/labels/a.txt",
                    content=b"0 0.5 0.5 0.2 0.2\n",
                ),
                UploadedFile(filename="data.yaml", content=b"names: [crack]\n"),
                UploadedFile(filename="train/images/empty.jpg", content=b"img-e"),
                UploadedFile(filename="train/labels/empty.txt", content=b"\n"),
                UploadedFile(filename="raw.jpg", content=b"img-raw"),
            ],
        )

        by_name = {item.file_name: item for item in result}
        assert by_name["a.jpg"].status == ImageStatus.VERIFIED
        assert by_name["empty.jpg"].status == ImageStatus.VERIFIED
        assert by_name["empty.jpg"].is_background is True
        assert by_name["raw.jpg"].status == ImageStatus.UNANNOTATED

        labeled = annotations.replaced[by_name["a.jpg"].id]
        assert len(labeled) == 1
        assert labeled[0].verification_status == VerificationStatus.VERIFIED
        assert labeled[0].source.value == "MANUAL"
        assert by_name["empty.jpg"].id not in annotations.replaced
        assert any(item.name == "crack" for item in class_repo.classes)
        assert uow.committed is True
        assert len(images.updated) >= 2

    @pytest.mark.asyncio
    async def test_classification_upload_rejects_yolo_labels(self) -> None:
        project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
        use_case, _images, _metadata, uow, _project, annotations, class_repo = _use_case(
            project
        )
        with pytest.raises(TaskTypeMismatchException):
            await use_case.execute(
                project.id,
                [
                    UploadedFile(filename="a.jpg", content=b"img-a"),
                    UploadedFile(filename="a.txt", content=b"0 0.5 0.5 0.2 0.2\n"),
                    UploadedFile(filename="data.yaml", content=b"names: [crack]\n"),
                ],
            )
        assert annotations.replaced == {}
        assert class_repo.classes == []
        assert uow.committed is False

    @pytest.mark.asyncio
    async def test_classification_upload_allows_plain_images(self) -> None:
        project = Project.create("Cls", task_type=ProjectTaskType.CLASSIFICATION)
        use_case, _images, _metadata, uow, _project, annotations, _class_repo = _use_case(
            project
        )
        result = await use_case.execute(
            project.id,
            [UploadedFile(filename="plain.jpg", content=b"img")],
        )
        assert result[0].status == ImageStatus.UNANNOTATED
        assert annotations.replaced == {}
        assert uow.committed is True

    @pytest.mark.asyncio
    async def test_reuses_existing_class_by_name(self) -> None:
        project = Project.create("Demo")
        existing = AnnotationClass.create(
            project_id=project.id,
            name="crack",
            color_hex="#FF0000",
            index_id=0,
        )
        use_case, _, _, _, _, annotations, class_repo = _use_case(
            project, classes=[existing]
        )
        result = await use_case.execute(
            project.id,
            [
                UploadedFile(filename="a.png", content=b"img"),
                UploadedFile(filename="a.txt", content=b"0 0.4 0.4 0.1 0.1\n"),
                UploadedFile(filename="classes.txt", content=b"crack\n"),
            ],
        )
        assert len(class_repo.classes) == 1
        assert annotations.replaced[result[0].id][0].class_id == existing.id

    @pytest.mark.asyncio
    async def test_rejects_missing_project(self) -> None:
        use_case, *_ = _use_case()
        with pytest.raises(ResourceNotFoundException):
            await use_case.execute(
                uuid4(),
                [UploadedFile(filename="a.png", content=b"x")],
            )

    @pytest.mark.asyncio
    async def test_rejects_unsupported_format(self) -> None:
        use_case, _, _, uow, project, *_ = _use_case()
        with pytest.raises(DomainValidationException, match="format"):
            await use_case.execute(
                project.id,
                [UploadedFile(filename="notes.pdf", content=b"nope")],
            )
        assert uow.committed is False

    @pytest.mark.asyncio
    async def test_allows_same_stem_across_roboflow_splits(self) -> None:
        use_case, _, _, uow, project, annotations, _ = _use_case()
        result = await use_case.execute(
            project.id,
            [
                UploadedFile(filename="train/images/x.png", content=b"one"),
                UploadedFile(filename="train/labels/x.txt", content=b"0 0.5 0.5 0.1 0.1\n"),
                UploadedFile(filename="valid/images/x.png", content=b"two"),
                UploadedFile(filename="valid/labels/x.txt", content=b"\n"),
                UploadedFile(filename="classes.txt", content=b"obj\n"),
            ],
        )
        by_path = {item.file_name: item for item in result}
        # Storage may UUID-suffix one of the colliding basenames.
        assert len(result) == 2
        verified = [item for item in result if item.status.value == "VERIFIED"]
        assert len(verified) == 2
        backgrounds = [item for item in result if item.is_background]
        assert len(backgrounds) == 1
        assert sum(len(boxes) for boxes in annotations.replaced.values()) == 1
        assert uow.committed is True

    @pytest.mark.asyncio
    async def test_cleans_up_files_when_persist_fails(self) -> None:
        project = Project.create("Demo")
        images = _FakeImages()

        async def boom(items):
            raise RuntimeError("db down")

        images.add_many = boom  # type: ignore[method-assign]
        storage = _FakeStorage()
        use_case = UploadImagesUseCase(
            projects=_FakeProjects(project),
            images=images,
            storage=storage,
            metadata=_FakeMetadata(),
            uow=_FakeUow(),
            annotations=_FakeAnnotations(),
            classes=_FakeClasses(),
        )
        with pytest.raises(RuntimeError, match="db down"):
            await use_case.execute(
                project.id,
                [UploadedFile(filename="ok.png", content=b"one")],
            )
        assert storage.deleted
        assert storage.deleted[0].endswith("ok.png")

    @pytest.mark.asyncio
    async def test_rejects_oversized_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.application.use_cases.images import upload_images as upload_mod

        monkeypatch.setattr(upload_mod, "MAX_UPLOAD_BYTES", 8)
        use_case, _, _, uow, project, *_ = _use_case()
        with pytest.raises(DomainValidationException, match="size"):
            await use_case.execute(
                project.id,
                [UploadedFile(filename="big.png", content=b"0123456789")],
            )
        assert uow.committed is False

    @pytest.mark.asyncio
    async def test_allows_zip_larger_than_image_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io
        import zipfile

        from app.application.use_cases.images import upload_images as upload_mod

        monkeypatch.setattr(upload_mod, "MAX_UPLOAD_BYTES", 8)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("cat.png", b"image-bytes")
            archive.writestr("data.yaml", b"names: [cat]\n")
        payload = buf.getvalue()
        assert len(payload) > 8
        monkeypatch.setattr(upload_mod, "MAX_UPLOAD_ZIP_BYTES", len(payload) + 8)
        use_case, images, _, uow, project, *_ = _use_case()
        result = await use_case.execute(
            project.id,
            [UploadedFile(filename="bundle.zip", content=payload)],
        )
        assert len(result) == 1
        assert images.added == result
        assert uow.committed is True

    @pytest.mark.asyncio
    async def test_rejects_oversized_zip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.application.use_cases.images import upload_images as upload_mod

        monkeypatch.setattr(upload_mod, "MAX_UPLOAD_ZIP_BYTES", 8)
        use_case, _, _, uow, project, *_ = _use_case()
        with pytest.raises(DomainValidationException, match="size"):
            await use_case.execute(
                project.id,
                [UploadedFile(filename="big.zip", content=b"0123456789")],
            )
        assert uow.committed is False

    @pytest.mark.asyncio
    async def test_reads_image_bytes_from_body_path(self, tmp_path) -> None:
        image_path = tmp_path / "a.png"
        image_path.write_bytes(b"from-disk")
        use_case, images, metadata, uow, project, *_ = _use_case()
        result = await use_case.execute(
            project.id,
            [UploadedFile(filename="shots/a.png", body_path=str(image_path))],
        )
        assert len(result) == 1
        assert metadata.seen == [b"from-disk"]
        assert images.added == result
        assert uow.committed is True

    @pytest.mark.asyncio
    async def test_rejects_too_many_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.application.use_cases.images import upload_images as upload_mod

        monkeypatch.setattr(upload_mod, "MAX_UPLOAD_FILES", 2)
        use_case, _, _, uow, project, *_ = _use_case()
        with pytest.raises(DomainValidationException, match="too many files"):
            await use_case.execute(
                project.id,
                [
                    UploadedFile(filename="a.png", content=b"one"),
                    UploadedFile(filename="b.png", content=b"two"),
                    UploadedFile(filename="c.png", content=b"three"),
                ],
            )
        assert uow.committed is False

    @pytest.mark.asyncio
    async def test_imports_classes_from_classes_txt_when_yaml_names_missing(
        self,
    ) -> None:
        use_case, _, _, uow, project, annotations, class_repo = _use_case()
        result = await use_case.execute(
            project.id,
            [
                UploadedFile(filename="images/a.jpg", content=b"img"),
                UploadedFile(filename="labels/a.txt", content=b"0 0.5 0.5 0.1 0.1\n"),
                UploadedFile(
                    filename="data.yaml",
                    content=b"nc: 1\nnames:\n0: shifted\n",
                ),
                UploadedFile(filename="classes.txt", content=b"lamp\n"),
            ],
        )
        assert any(item.name == "lamp" for item in class_repo.classes)
        assert not any(item.name == "shifted" for item in class_repo.classes)
        assert annotations.replaced[result[0].id][0].class_id == next(
            item.id for item in class_repo.classes if item.name == "lamp"
        )
        assert uow.committed is True

    @pytest.mark.asyncio
    async def test_rejects_unknown_class_index(self) -> None:
        use_case, _, _, uow, project, *_ = _use_case()
        with pytest.raises(DomainValidationException, match="class index"):
            await use_case.execute(
                project.id,
                [
                    UploadedFile(filename="a.png", content=b"img"),
                    UploadedFile(filename="a.txt", content=b"3 0.5 0.5 0.1 0.1\n"),
                    UploadedFile(filename="classes.txt", content=b"only\n"),
                ],
            )
        assert uow.committed is False
