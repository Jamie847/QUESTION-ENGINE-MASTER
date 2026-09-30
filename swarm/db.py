from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from swarm.orm import Base
from swarm.settings import get_settings

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"future": True}
        if settings.sqlalchemy_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(settings.sqlalchemy_url, **kwargs)
        if settings.sqlalchemy_url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _sqlite_pragma(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()

        _Session = sessionmaker(_engine, expire_on_commit=False, future=True)
    return _engine


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    _migrate_digest_uniqueness(engine)
    _migrate_wo006(engine)


def _migrate_digest_uniqueness(engine: Engine) -> None:
    """Date-unique digests silently replaced a same-day run. One digest per run."""
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE digests DROP CONSTRAINT IF EXISTS uq_digest_date"))
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_digest_run ON digests (run_id)")
            )
            return
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        if "digests_old_date_unique" in tables:
            if "digests" in tables:
                conn.execute(text("DROP TABLE IF EXISTS digests_old_date_unique"))
            else:
                conn.execute(text("ALTER TABLE digests_old_date_unique RENAME TO digests"))
        indexes = conn.execute(text("PRAGMA index_list('digests')")).mappings().all()
        names = {str(row["name"]) for row in indexes}
        if "uq_digest_date" in names:
            conn.execute(text("DROP INDEX IF EXISTS uq_digest_date"))
        date_unique = False
        for idx in indexes:
            if not idx.get("unique"):
                continue
            cols = conn.execute(
                text(f"PRAGMA index_info('{idx['name']}')")
            ).mappings().all()
            if [c.get("name") for c in cols] == ["date"]:
                date_unique = True
        schema = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='digests'")
        ).scalar()
        normalized = (schema or "").replace(" ", "").lower()
        if date_unique or "unique(date)" in normalized:
            conn.execute(text("ALTER TABLE digests RENAME TO digests_old_date_unique"))
            conn.execute(
                text(
                    """
                    CREATE TABLE digests (
                        id INTEGER NOT NULL PRIMARY KEY,
                        run_id INTEGER NOT NULL,
                        date VARCHAR(16) NOT NULL,
                        title TEXT NOT NULL,
                        markdown TEXT NOT NULL,
                        top_ids JSON,
                        curated_count INTEGER,
                        killed_count INTEGER,
                        rejected_intersection_count INTEGER,
                        degraded BOOLEAN,
                        warnings JSON,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (run_id)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO digests (
                        id, run_id, date, title, markdown, top_ids,
                        curated_count, killed_count, rejected_intersection_count,
                        degraded, warnings, created_at
                    )
                    SELECT
                        id, run_id, date, title, markdown, top_ids,
                        curated_count, killed_count, rejected_intersection_count,
                        degraded, warnings, created_at
                    FROM digests_old_date_unique
                    """
                )
            )
            conn.execute(text("DROP TABLE digests_old_date_unique"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_digest_run ON digests (run_id)"))


def _migrate_wo006(engine: Engine) -> None:
    """Add honesty columns. Existing questions are marked pre-wo006; links are not repaired."""
    specs: list[tuple[str, str, str]] = [
        ("questions", "provenance", "VARCHAR(32)"),
        ("questions", "written_by", "VARCHAR(128)"),
        ("questions", "promoted_at", "TIMESTAMP"),
        ("briefs", "written_by", "VARCHAR(128)"),
        ("intersections", "written_by", "VARCHAR(128)"),
        ("runs", "curated_by", "VARCHAR(128)"),
        ("ratings", "why", "TEXT"),
    ]
    json_type = "JSON" if engine.dialect.name == "postgresql" else "TEXT"
    specs.append(("runs", "scout_seen", json_type))
    with engine.begin() as conn:
        for table, column, ddl in specs:
            if column in _column_names(conn, engine, table):
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        conn.execute(
            text(
                "UPDATE questions SET provenance = 'pre-wo006' "
                "WHERE provenance IS NULL OR provenance = ''"
            )
        )


def _column_names(conn, engine: Engine, table: str) -> set[str]:
    if engine.dialect.name == "postgresql":
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table"
            ),
            {"table": table},
        ).all()
        return {str(row[0]) for row in rows}
    rows = conn.execute(text(f"PRAGMA table_info('{table}')")).all()
    return {str(row[1]) for row in rows}


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _Session is not None
    session = _Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping_db() -> bool:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
