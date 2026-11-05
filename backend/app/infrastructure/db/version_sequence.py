"""Atomic version-number reservation.

MAX(version_number)+1 is not safe: two transactions can read the same max
before either insert lands. A committed sequence row closes that window.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.tables import VersionSequenceRow

_RESERVE_ATTEMPTS = 8


async def reserve_version_number(
    session: AsyncSession,
    project_id: UUID,
    kind: str,
    version_table,
) -> int:
    """Return a version number no other committed reservation holds.

    Any open read transaction on this session is committed first so the
    reservation write is not blocked by our own shared lock. The reservation
    itself is committed before returning.
    """
    if session.in_transaction():
        await session.commit()

    pid = str(project_id)
    for _ in range(_RESERVE_ATTEMPTS):
        current_seq = await session.scalar(
            select(VersionSequenceRow.last_number).where(
                VersionSequenceRow.project_id == pid,
                VersionSequenceRow.kind == kind,
            )
        )
        current_max = await session.scalar(
            select(func.max(version_table.version_number)).where(
                version_table.project_id == pid
            )
        )
        nxt = max(int(current_seq or 0), int(current_max or 0)) + 1
        try:
            if current_seq is None:
                session.add(
                    VersionSequenceRow(
                        project_id=pid,
                        kind=kind,
                        last_number=nxt,
                    )
                )
            else:
                reserved = await session.scalar(
                    update(VersionSequenceRow)
                    .where(
                        VersionSequenceRow.project_id == pid,
                        VersionSequenceRow.kind == kind,
                        VersionSequenceRow.last_number == int(current_seq),
                    )
                    .values(last_number=nxt)
                    .returning(VersionSequenceRow.last_number)
                )
                if reserved is None:
                    await session.rollback()
                    continue
            await session.commit()
            return nxt
        except IntegrityError:
            await session.rollback()
            continue

    raise RuntimeError(
        f"could not reserve {kind} version number for project {project_id}"
    )
