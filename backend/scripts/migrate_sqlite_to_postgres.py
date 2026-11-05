"""Copy lblstdio's current SQLite database into an empty PostgreSQL database.

Run with the backend virtualenv after stopping the application:
  python scripts/migrate_sqlite_to_postgres.py --source sqlite+aiosqlite:///app.db \
      --target postgresql+asyncpg://user:password@localhost:5432/lblstdio

Image files, model weights and generated datasets remain in storage and are not copied.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import timezone
from pathlib import Path
import sys

from sqlalchemy import DateTime, Integer, and_, func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.db.session import init_schema
from app.infrastructure.db.tables import Base

BATCH_SIZE = 1000


def normalize_row(row, table):
    values = dict(row)
    for column in table.columns:
        value = values.get(column.name)
        if value is not None and isinstance(column.type, DateTime) and column.type.timezone:
            if value.tzinfo is None:
                values[column.name] = value.replace(tzinfo=timezone.utc)
    return values


async def migrate(source_url: str, target_url: str) -> None:
    if not source_url.startswith("sqlite"):
        raise ValueError("The source must be a SQLite URL")
    if not target_url.startswith("postgresql+"):
        raise ValueError("The target must be an async PostgreSQL URL, for example postgresql+asyncpg://...")

    source = create_async_engine(source_url)
    target = create_async_engine(target_url)
    try:
        # Applies the same SQLite schema updates as a normal application startup.
        await init_schema(source)
        await init_schema(target)

        async with target.connect() as conn:
            counts = {
                table.name: await conn.scalar(select(func.count()).select_from(table))
                for table in Base.metadata.sorted_tables
            }
        populated = {name: count for name, count in counts.items() if count}
        if populated:
            raise RuntimeError(f"Target database is not empty: {populated}. Use a new, empty database.")

        legacy_orphans = []
        async with source.connect() as source_conn, target.begin() as target_conn:
            preparer = target.dialect.identifier_preparer
            for table in Base.metadata.sorted_tables:
                for fk in table.foreign_key_constraints:
                    elements = list(fk.elements)
                    remote_table = elements[0].column.table
                    join_on = and_(*(element.parent == element.column for element in elements))
                    missing = and_(*(element.parent.is_not(None) for element in elements),
                                   *(element.column.is_(None) for element in elements))
                    orphan_count = await source_conn.scalar(
                        select(func.count()).select_from(table.outerjoin(remote_table, join_on)).where(missing)
                    )
                    if not orphan_count:
                        continue
                    local_columns = "_".join(element.parent.name for element in elements)
                    constraint_name = fk.name or f"{table.name}_{local_columns}_fkey"
                    await target_conn.execute(text(
                        f"ALTER TABLE {preparer.quote(table.name)} DROP CONSTRAINT {preparer.quote(constraint_name)}"
                    ))
                    legacy_orphans.append((table, elements, constraint_name, orphan_count))

        for table, _elements, _constraint_name, orphan_count in legacy_orphans:
            print(f"Preserving {orphan_count} legacy rows in {table.name} with missing referenced rows; new references remain constrained.")

        async with source.connect() as source_conn:
            for table in Base.metadata.sorted_tables:
                expected = await source_conn.scalar(select(func.count()).select_from(table))
                if not expected:
                    print(f"{table.name}: 0 rows")
                    continue
                copied = 0
                async with target.begin() as target_conn:
                    result = await source_conn.stream(select(table))
                    batch = []
                    async for row in result.mappings():
                        batch.append(normalize_row(row, table))
                        if len(batch) >= BATCH_SIZE:
                            await target_conn.execute(table.insert(), batch)
                            copied += len(batch)
                            batch.clear()
                    if batch:
                        await target_conn.execute(table.insert(), batch)
                        copied += len(batch)
                print(f"{table.name}: {copied}/{expected} rows")
                if copied != expected:
                    raise RuntimeError(f"Row count changed during migration for {table.name}; stop the application and retry with a fresh target.")

        async with target.begin() as conn:
            preparer = target.dialect.identifier_preparer
            for table, elements, constraint_name, _orphan_count in legacy_orphans:
                cols = ", ".join(preparer.quote(e.parent.name) for e in elements)
                remote_cols = ", ".join(preparer.quote(e.column.name) for e in elements)
                remote_table = preparer.quote(elements[0].column.table.name)
                on_delete = f" ON DELETE {elements[0].ondelete}" if elements[0].ondelete else ""
                await conn.execute(text(
                    f"ALTER TABLE {preparer.quote(table.name)} ADD CONSTRAINT {preparer.quote(constraint_name)} "
                    f"FOREIGN KEY ({cols}) REFERENCES {remote_table} ({remote_cols}){on_delete} NOT VALID"
                ))
            for table in Base.metadata.sorted_tables:
                for column in table.columns:
                    if not column.primary_key or not isinstance(column.type, Integer):
                        continue
                    sequence = await conn.scalar(text("SELECT pg_get_serial_sequence(:table, :column)"), {"table": table.name, "column": column.name})
                    if sequence:
                        max_value = await conn.scalar(select(func.max(column)).select_from(table))
                        if max_value is not None:
                            await conn.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, true)"), {"sequence": sequence, "value": max_value})
        print("Migration complete. Source SQLite database was preserved.")
    finally:
        await source.dispose()
        await target.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="SQLite async URL")
    parser.add_argument("--target", required=True, help="PostgreSQL async URL")
    args = parser.parse_args()
    asyncio.run(migrate(args.source, args.target))


if __name__ == "__main__":
    main()
