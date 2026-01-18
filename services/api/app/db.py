"""Database bootstrap.

Pytest imports the FastAPI app and creates a `TestClient` at module import time
in `services/api/app/tests/test_api.py`. In that pattern, Starlette/FastAPI
startup events are *not guaranteed* to run before the first request.

To make the API tests reliable both on the host (pytest outside docker) and
inside docker compose profiles, we ensure the schema exists lazily the first
time a DB session is requested.
"""
from __future__ import annotations

from threading import Lock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.settings import settings


DEFAULT_DB_USER_ID = 'local'
DEFAULT_DB_DISPLAY_NAME = 'local'
DEFAULT_DB_ROLE = 'local_user'


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    ...


_init_lock = Lock()
_init_done = False


def init_db() -> None:
    """Create required extensions + tables if missing (idempotent)."""

    global _init_done

    if _init_done:
        return

    with _init_lock:
        if _init_done:
            return

        # Import models so SQLAlchemy registers tables on Base.metadata.
        # (Local import to avoid import cycles.)
        from app import models  # noqa: F401

        # Postgres-only: pgvector is needed for Vector columns.
        # If the extension isn't available, table creation can fail.
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:
            # In some environments the extension may not be installable.
            # We'll still attempt table creation; if Vector columns exist and
            # the DB can't handle them, tests will surface that clearly.
            pass

        Base.metadata.create_all(bind=engine)

        # Seed required dimension rows (idempotent)
        with engine.begin() as conn:
            # Ensure pgvector extension if you use it
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

            # Create tables
            Base.metadata.create_all(bind=conn)

            # Seed dim_user so fact_prompt.user_id FK won't fail in tests
            conn.execute(
                text("""
                    INSERT INTO dim_user (user_id, display_name, role)
                    VALUES (:user_id, :display_name, :role)
                    ON CONFLICT (user_id) DO NOTHING
                """),
                {
                    "user_id": DEFAULT_DB_USER_ID,
                    'display_name': DEFAULT_DB_DISPLAY_NAME,
                    'role': DEFAULT_DB_ROLE
                },
            )


        _init_done = True


def get_db():
    # Ensure schema exists even if FastAPI startup didn't run.
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
