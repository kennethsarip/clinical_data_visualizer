"""Apply the numbered SQL files in `migrations/` in order (CLAUDE.md §6).

Run: `uv run --env-file .env python -m app.migrate`. Every unapplied file runs inside one
transaction, so a failing file leaves the database exactly as it was. Applied files are recorded
in `schema_migrations`, so a second run is a no-op.
"""

import logging
import re
from pathlib import Path

import psycopg

from app.config import load_database_url

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

_FILENAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")

# The ledger is created here rather than in a migration file: it must exist before the runner
# can tell which files are unapplied.
_LEDGER_DDL = b"""
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   text        PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(RuntimeError):
    """The migrations directory holds a misnamed or duplicate-numbered file."""


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    """Return the migration files sorted by number, rejecting names the runner would misorder."""
    files: dict[str, Path] = {}
    for path in directory.glob("*.sql"):
        match = _FILENAME.match(path.name)
        if match is None:
            raise MigrationError(f"{path.name}: expected NNN_lowercase_name.sql")
        number = match.group(1)
        if number in files:
            raise MigrationError(f"{path.name} and {files[number].name} share number {number}")
        files[number] = path
    return [files[number] for number in sorted(files)]


def apply_migrations(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every unapplied file in one transaction; return the filenames applied."""
    files = migration_files(directory)
    applied_now: list[str] = []
    with conn.transaction():
        conn.execute(_LEDGER_DDL)
        applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}
        for path in files:
            if path.name in applied:
                continue
            # bytes, not str: the SQL comes from a repo file, and psycopg's typing only
            # accepts literal strings as raw queries.
            conn.execute(path.read_bytes())
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
            applied_now.append(path.name)
    return applied_now


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with psycopg.connect(load_database_url(), autocommit=True) as conn:
        applied = apply_migrations(conn)
    if applied:
        logger.info("Applied %d migration(s): %s", len(applied), ", ".join(applied))
    else:
        logger.info("Database is up to date; nothing to apply")


if __name__ == "__main__":
    main()
