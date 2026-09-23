"""Per-attempt staging directories for dataset and model publication."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from app.application.ports.storage.file_storage import IFileStorage

logger = logging.getLogger(__name__)


def attempt_staging_dir(project_id: UUID, bucket: str) -> str:
    """Private directory for one publication attempt. Never shared as vN."""
    return f"projects/{project_id}/{bucket}/_staging/{uuid4()}"


def published_version_dir(project_id: UUID, bucket: str, version_number: int) -> str:
    return f"projects/{project_id}/{bucket}/v{version_number}"


async def publish_attempt(
    storage: IFileStorage, staging_rel: str, published_rel: str
) -> None:
    """Atomically move this attempt's tree onto its reserved vN path."""
    await storage.move_directory(staging_rel, published_rel)


async def cleanup_attempt(
    storage: IFileStorage,
    staging_rel: str,
    published_rel: str | None,
) -> None:
    """Remove only this attempt's files.

    A directory already published as vN is deleted only after it is moved back
    onto this attempt's private staging path. If that move fails, the published
    tree is left in place.
    """
    owned = staging_rel
    if published_rel is not None:
        try:
            await storage.move_directory(published_rel, staging_rel)
        except Exception:
            logger.warning(
                "left published directory %s in place; it could not be moved back",
                published_rel,
                exc_info=True,
            )
            return
        owned = staging_rel
    try:
        await storage.delete_directory(owned)
    except Exception:
        logger.warning("failed to delete staging %s", owned, exc_info=True)
