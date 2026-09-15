from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.infrastructure.db.tables import Base

_DATASET_VERSION_COLUMNS = (
    ("train_file_count", "INTEGER NOT NULL DEFAULT 0"),
    ("valid_file_count", "INTEGER NOT NULL DEFAULT 0"),
    ("test_file_count", "INTEGER NOT NULL DEFAULT 0"),
)

_TRAINING_JOB_COLUMNS = (
    ("patience", "INTEGER NOT NULL DEFAULT 20"),
    ("stopped_early", "INTEGER NOT NULL DEFAULT 0"),
)

_IMAGE_COLUMNS = (
    ("is_background", "INTEGER NOT NULL DEFAULT 0"),
)

_MODEL_VERSION_COLUMNS = (
    ("name", "TEXT NOT NULL DEFAULT ''"),
)


def create_engine(database_url: str) -> AsyncEngine:
    kwargs: dict = {"echo": False}
    if ":memory:" in database_url:
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    else:
        db_path = database_url.split("///")[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(database_url, **kwargs)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _ensure_sqlite_columns(connection) -> None:
    _ensure_table_columns(connection, "dataset_versions", _DATASET_VERSION_COLUMNS)
    _ensure_table_columns(connection, "training_jobs", _TRAINING_JOB_COLUMNS)
    _ensure_table_columns(connection, "images", _IMAGE_COLUMNS)
    _ensure_table_columns(connection, "model_versions", _MODEL_VERSION_COLUMNS)


def _ensure_table_columns(connection, table: str, columns: tuple[tuple[str, str], ...]) -> None:
    existing = {
        row[1]
        for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
    }
    if not existing:
        return
    for name, ddl in columns:
        if name not in existing:
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


async def init_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_ensure_sqlite_columns)


async def create_session_factory(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    await init_schema(engine)
    factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )
    return engine, factory


async def dispose_engine(engine: AsyncEngine) -> None:
    await engine.dispose()
