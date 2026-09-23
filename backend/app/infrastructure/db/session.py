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
    ("test_metrics", "TEXT"),
)

_IMAGE_COLUMNS = (
    ("is_background", "INTEGER NOT NULL DEFAULT 0"),
)

_MODEL_VERSION_COLUMNS = (
    ("name", "TEXT NOT NULL DEFAULT ''"),
    ("top1", "FLOAT"),
    ("test_metrics", "TEXT"),
)

_PROJECT_COLUMNS = (
    ("task_type", "VARCHAR(32) NOT NULL DEFAULT 'DETECTION'"),
)

_AUTO_LABEL_JOB_COLUMNS = (
    ("iou_threshold", "FLOAT NOT NULL DEFAULT 0.7"),
    ("consistency_iou_threshold", "FLOAT NOT NULL DEFAULT 0.8"),
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
    _ensure_table_columns(connection, "auto_label_jobs", _AUTO_LABEL_JOB_COLUMNS)
    _ensure_table_columns(connection, "projects", _PROJECT_COLUMNS)
    _ensure_model_versions_nullable_fks(connection)


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


def _ensure_model_versions_nullable_fks(connection) -> None:
    """SQLite cannot ALTER NOT NULL → NULL; rebuild table when needed."""
    info = list(connection.exec_driver_sql("PRAGMA table_info(model_versions)"))
    if not info:
        return
    by_name = {row[1]: row for row in info}
    dataset_col = by_name.get("dataset_version_id")
    job_col = by_name.get("training_job_id")
    if dataset_col is None or job_col is None:
        return
    # row[3] is notnull flag (1 = NOT NULL)
    if int(dataset_col[3]) == 0 and int(job_col[3]) == 0:
        return

    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.exec_driver_sql(
        """
        CREATE TABLE model_versions__nullable (
            id VARCHAR(36) NOT NULL,
            project_id VARCHAR(36) NOT NULL,
            dataset_version_id VARCHAR(36),
            training_job_id VARCHAR(36),
            version_number INTEGER NOT NULL,
            name VARCHAR(255) NOT NULL DEFAULT '',
            weights_path VARCHAR(1024) NOT NULL,
            map50 FLOAT,
            map50_95 FLOAT,
            precision FLOAT,
            recall FLOAT,
            top1 FLOAT,
            test_metrics TEXT,
            is_active_for_stream INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_model_version_project_number
                UNIQUE (project_id, version_number)
        )
        """
    )
    connection.exec_driver_sql(
        """
        INSERT INTO model_versions__nullable (
            id, project_id, dataset_version_id, training_job_id, version_number,
            name, weights_path, map50, map50_95, precision, recall,
            top1, test_metrics, is_active_for_stream, created_at
        )
        SELECT
            id, project_id, dataset_version_id, training_job_id, version_number,
            COALESCE(name, ''), weights_path, map50, map50_95, precision, recall,
            NULL, NULL, is_active_for_stream, created_at
        FROM model_versions
        """
    )
    connection.exec_driver_sql("DROP TABLE model_versions")
    connection.exec_driver_sql(
        "ALTER TABLE model_versions__nullable RENAME TO model_versions"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_model_versions_project_id "
        "ON model_versions (project_id)"
    )
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")


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
