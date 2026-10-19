"""Copy a consistent SQLite backup to the configured PostgreSQL, without rewriting history."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from aurelia_fx.postgres_memory import JOURNAL_TABLES, PostgresMemory  # noqa: E402
from aurelia_fx.storage import database_url  # noqa: E402


def migrate(source: Path, backup_dir: Path) -> dict:
    from psycopg import sql

    url = database_url()
    if not url:
        raise RuntimeError("PostgreSQL configuration missing")
    if not source.is_file():
        raise FileNotFoundError(source)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = (
        backup_dir / f"memory-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.sqlite3"
    )
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(backup) as dest:
            original.backup(dest)
    report = {"backup": str(backup), "tables": {}}
    memory = PostgresMemory(url)
    try:
        with sqlite3.connect(backup) as source_db:
            source_db.row_factory = sqlite3.Row
            version = source_db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            if version != str(memory.SCHEMA_VERSION):
                raise ValueError(
                    "Migrate the source to the current schema before importing"
                )
            with memory.pool.connection() as pg:
                with pg.transaction():
                    pg.execute("SELECT pg_advisory_xact_lock_shared(70616003)")
                    pg.execute("SELECT pg_advisory_xact_lock(70616004)")
                    for table in JOURNAL_TABLES:
                        cursor = source_db.execute(f"SELECT * FROM {table}")
                        columns = [item[0] for item in cursor.description]
                        identity = columns[0]
                        temporary = sql.Identifier("import_" + table)
                        pg.execute(
                            sql.SQL(
                                "CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP"
                            ).format(temporary, sql.Identifier(table))
                        )
                        copied = 0
                        with pg.cursor() as target:
                            with target.copy(
                                sql.SQL("COPY {} ({}) FROM STDIN").format(
                                    temporary,
                                    sql.SQL(",").join(map(sql.Identifier, columns)),
                                )
                            ) as copy:
                                for row in cursor:
                                    encoded = row["payload_json"]
                                    if (
                                        hashlib.sha256(
                                            encoded.encode("utf-8")
                                        ).hexdigest()
                                        != row["payload_sha256"]
                                    ):
                                        raise ValueError(
                                            f"Source payload hash mismatch: {table}/{row[identity]}"
                                        )
                                    copy.write_row(tuple(row))
                                    copied += 1
                        mismatch = pg.execute(
                            sql.SQL(
                                "SELECT count(*) FROM {} s JOIN {} d USING ({}) WHERE s.payload_sha256 <> d.payload_sha256"
                            ).format(
                                temporary,
                                sql.Identifier(table),
                                sql.Identifier(identity),
                            )
                        ).fetchone()["count"]
                        if mismatch:
                            raise ValueError(f"Conflicting immutable IDs in {table}")
                        inserted = pg.execute(
                            sql.SQL(
                                "INSERT INTO {} SELECT * FROM {} ON CONFLICT DO NOTHING"
                            ).format(sql.Identifier(table), temporary)
                        ).rowcount
                        matched = pg.execute(
                            sql.SQL(
                                "SELECT count(*) FROM {} s JOIN {} d USING ({}) WHERE s.payload_sha256 = d.payload_sha256"
                            ).format(
                                temporary,
                                sql.Identifier(table),
                                sql.Identifier(identity),
                            )
                        ).fetchone()["count"]
                        if matched != copied:
                            raise RuntimeError(f"Incomplete migration: {table}")
                        report["tables"][table] = {
                            "source": copied,
                            "inserted": inserted,
                            "matched_hashes": matched,
                        }
                    pg.execute(
                        "INSERT INTO metadata(key,value) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                        (
                            "sqlite_migration_" + backup.stem,
                            json.dumps(report, sort_keys=True),
                        ),
                    )
    finally:
        memory.close()
    (backup_dir / (backup.stem + ".json")).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=ROOT / "data/agent_memory.sqlite3"
    )
    parser.add_argument(
        "--backup-dir", type=Path, default=ROOT / "data/database_backups"
    )
    args = parser.parse_args()
    print(json.dumps(migrate(args.source, args.backup_dir), indent=2))
