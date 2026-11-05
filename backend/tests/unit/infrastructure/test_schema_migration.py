import pytest
from sqlalchemy import inspect

from app.infrastructure.db.session import _ensure_project_assignments, create_engine, init_schema


class _Postgres:
    class dialect:
        name = "postgresql"

    def __init__(self):
        self.sql = []

    def exec_driver_sql(self, statement):
        self.sql.append(statement)


def test_postgres_migration_creates_assignment_table_and_task_user():
    connection = _Postgres()
    _ensure_project_assignments(connection)
    text = "\n".join(connection.sql)
    assert "CREATE TABLE IF NOT EXISTS project_annotators" in text
    assert "REFERENCES projects" in text and "REFERENCES users" in text
    assert "ALTER TABLE annotation_tasks ADD COLUMN IF NOT EXISTS user_id" in text
    assert "ix_annotation_tasks_user_id" in text


@pytest.mark.asyncio
async def test_sqlite_migration_restores_removed_assignment_schema(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}")
    await init_schema(engine)
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: sync.exec_driver_sql("DROP INDEX IF EXISTS ix_annotation_tasks_user_id"))
        await connection.run_sync(lambda sync: sync.exec_driver_sql("ALTER TABLE annotation_tasks DROP COLUMN user_id"))
        await connection.run_sync(lambda sync: sync.exec_driver_sql("DROP TABLE project_annotators"))
    await init_schema(engine)

    async with engine.connect() as connection:
        def columns(sync):
            info = inspect(sync)
            return {
                "tasks": {column["name"] for column in info.get_columns("annotation_tasks")},
                "links": info.get_table_names(),
            }
        found = await connection.run_sync(columns)
    assert "user_id" in found["tasks"]
    assert "project_annotators" in found["links"]
    await engine.dispose()
