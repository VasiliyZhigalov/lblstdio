from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


def dialect_insert(session, table):
    """Return an INSERT builder with ON CONFLICT support for the active backend."""
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        return sqlite_insert(table)
    if dialect == "postgresql":
        return postgresql_insert(table)
    raise RuntimeError(f"Unsupported database dialect: {dialect}")
