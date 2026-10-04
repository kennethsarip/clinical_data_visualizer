from pathlib import Path

import psycopg
import pytest

from app.migrate import MigrationError, apply_migrations, migration_files


def _tables(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
    )
    return {row[0] for row in rows}


def _ledger(conn: psycopg.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT filename FROM schema_migrations ORDER BY 1")]


def _write(directory: Path, files: dict[str, str]) -> Path:
    for name, body in files.items():
        (directory / name).write_text(body)
    return directory


# --- file discovery (no database) ---


def test_files_sort_by_number(tmp_path: Path) -> None:
    _write(tmp_path, {"010_c.sql": "", "002_b.sql": "", "001_a.sql": ""})
    assert [p.name for p in migration_files(tmp_path)] == ["001_a.sql", "002_b.sql", "010_c.sql"]


@pytest.mark.parametrize("name", ["1_short.sql", "001-dash.sql", "001_Upper.sql", "cache.sql"])
def test_misnamed_file_is_rejected(tmp_path: Path, name: str) -> None:
    _write(tmp_path, {name: ""})
    with pytest.raises(MigrationError):
        migration_files(tmp_path)


def test_duplicate_number_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, {"001_a.sql": "", "001_b.sql": ""})
    with pytest.raises(MigrationError, match="share number 001"):
        migration_files(tmp_path)


# --- applying (needs Postgres) ---


def test_repo_migrations_create_the_cache_tables(db: psycopg.Connection) -> None:
    assert apply_migrations(db) == ["001_cache.sql"]
    assert _tables(db) == {"api_pages", "trials", "schema_migrations"}
    assert _ledger(db) == ["001_cache.sql"]


def test_second_run_is_a_no_op(db: psycopg.Connection) -> None:
    apply_migrations(db)
    assert apply_migrations(db) == []
    assert _ledger(db) == ["001_cache.sql"]


def test_only_new_files_apply(db: psycopg.Connection, tmp_path: Path) -> None:
    _write(tmp_path, {"001_a.sql": "CREATE TABLE a (id int);"})
    apply_migrations(db, tmp_path)
    # 002 depends on 001's table, so it only succeeds if 001 is skipped, not re-run.
    _write(tmp_path, {"002_b.sql": "ALTER TABLE a ADD COLUMN note text;"})
    assert apply_migrations(db, tmp_path) == ["002_b.sql"]


def test_failing_file_rolls_back_the_whole_run(db: psycopg.Connection, tmp_path: Path) -> None:
    _write(tmp_path, {"001_ok.sql": "CREATE TABLE ok (id int);", "002_bad.sql": "NOT SQL;"})
    with pytest.raises(psycopg.errors.SyntaxError):
        apply_migrations(db, tmp_path)
    assert _tables(db) == set()


# --- constraints the cache relies on (CLAUDE.md §6, §8.2) ---


def test_trials_rejects_malformed_nct_id(db: psycopg.Connection) -> None:
    apply_migrations(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO trials (nct_id, record) VALUES ('NCT123', '{}')")


def test_api_pages_key_is_params_and_page(db: psycopg.Connection) -> None:
    apply_migrations(db)
    insert = (
        "INSERT INTO api_pages (params_key, page_index, total_count, body) VALUES (%s, %s, 0, '{}')"
    )
    db.execute(insert, ("k", 0))
    db.execute(insert, ("k", 1))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, ("k", 0))
