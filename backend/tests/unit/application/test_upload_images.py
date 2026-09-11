from uuid import UUID, uuid4

import pytest

from app.application.dto import UploadedFile
from app.application.use_cases.images.upload_images import UploadImagesUseCase
from app.domain.entities.image import Image
from app.domain.entities.project import Project
from app.domain.enums import SplitType
from app.domain.exceptions import DomainValidationException, ResourceNotFoundException
from app.domain.value_objects.split_ratios import SplitRatios


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

    async def add_many(self, images: list[Image]) -> None:
        self.added.extend(images)


class _FakeUow:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def _use_case(project: Project | None = None) -> tuple[UploadImagesUseCase, _FakeImages, _FakeMetadata, _FakeUow]:
    project = project or Project.create("Demo")
    images = _FakeImages()
    metadata = _FakeMetadata()
    uow = _FakeUow()
    use_case = UploadImagesUseCase(
        projects=_FakeProjects(project),
        images=images,
        storage=_FakeStorage(),
        metadata=metadata,
        uow=uow,
    )
    return use_case, images, metadata, uow, project


class TestUploadImagesUseCase:
    @pytest.mark.asyncio
    async def test_splits_ten_images_70_20_10_and_reads_dimensions(self) -> None:
        use_case, images, metadata, uow, project = _use_case()
        files = [
            UploadedFile(filename=f"img_{index}.png", content=b"payload-%d" % index)
            for index in range(10)
        ]

        result = await use_case.execute(
            project.id,
            files,
            ratios=SplitRatios(train=0.7, valid=0.2, test=0.1),
        )

        splits = [item.split for item in result]
        assert splits.count(SplitType.TRAIN) == 7
        assert splits.count(SplitType.VALID) == 2
        assert splits.count(SplitType.TEST) == 1
        assert all(item.width == 320 and item.height == 240 for item in result)
        assert metadata.seen == [item.content for item in files]
        assert images.added == result
        assert uow.committed is True

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
        use_case, _, _, uow, project = _use_case()
        with pytest.raises(DomainValidationException, match="format"):
            await use_case.execute(
                project.id,
                [UploadedFile(filename="notes.txt", content=b"nope")],
            )
        assert uow.committed is False

    @pytest.mark.asyncio
    async def test_validates_all_files_before_saving(self) -> None:
        use_case, _, _, uow, project = _use_case()
        storage = use_case._storage
        with pytest.raises(DomainValidationException, match="format"):
            await use_case.execute(
                project.id,
                [
                    UploadedFile(filename="ok.png", content=b"one"),
                    UploadedFile(filename="bad.txt", content=b"two"),
                ],
            )
        assert storage.saved == []
        assert uow.committed is False

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
        use_case, _, _, uow, project = _use_case()
        with pytest.raises(DomainValidationException, match="size"):
            await use_case.execute(
                project.id,
                [UploadedFile(filename="big.png", content=b"0123456789")],
            )
        assert uow.committed is False
