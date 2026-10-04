import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql

# The docker-compose.yml database; CI sets DATABASE_URL to its own service container.
_LOCAL_DATABASE_URL = "postgresql://cheiron:cheiron@127.0.0.1:5432/cheiron"


@pytest.fixture
def db() -> Iterator[psycopg.Connection]:
    """A connection whose search_path is a fresh schema, dropped afterwards.

    Tests get an empty database without touching the cache tables in the dev database.
    """
    url = os.environ.get("DATABASE_URL") or _LOCAL_DATABASE_URL
    try:
        conn = psycopg.connect(url, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as exc:
        pytest.fail(f"Postgres unreachable at DATABASE_URL; run `docker compose up -d` ({exc})")
    schema = sql.Identifier(f"test_{uuid.uuid4().hex}")
    with conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        conn.execute(sql.SQL("SET search_path TO {}").format(schema))
        try:
            yield conn
        finally:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))
