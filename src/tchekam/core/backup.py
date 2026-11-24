import logging
import os
import subprocess
from collections.abc import Callable
from datetime import datetime

from django.conf import settings

from tchekam.core.redact import redact
from tchekam.core.storage import ObjectStore

logger = logging.getLogger(__name__)

# (argv, extra environment) -> dump bytes. Injected so tests never need pg_dump.
Runner = Callable[[list[str], dict[str, str]], bytes]


class BackupError(RuntimeError):
    pass


def pg_dump_runner(args: list[str], env: dict[str, str]) -> bytes:
    try:
        result = subprocess.run(
            args, env={**os.environ, **env}, capture_output=True, check=False, timeout=3600
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise BackupError(f"pg_dump could not run: {type(exc).__name__}") from None
    if result.returncode != 0:
        # The exception carries only the status; pg_dump's stderr goes to the (masked) log.
        logger.error("pg_dump failed: %s", redact(result.stderr.decode(errors="replace")))
        raise BackupError(f"pg_dump failed with status {result.returncode}")
    return result.stdout


def _connection_env(db: dict) -> dict[str, str]:
    # libpq reads these, so the password never appears in argv (visible in `ps`) or logs.
    return {
        "PGHOST": str(db.get("HOST", "")),
        "PGPORT": str(db.get("PORT", "")),
        "PGUSER": str(db.get("USER", "")),
        "PGPASSWORD": str(db.get("PASSWORD", "")),
        "PGDATABASE": str(db["NAME"]),
    }


def create_backup(
    store: ObjectStore, *, now: datetime, runner: Runner | None = None, db: dict | None = None
) -> str:
    """Dump the database with pg_dump and upload it to the object store; returns the key."""
    runner = runner or pg_dump_runner
    db = db or settings.DATABASES["default"]
    # Custom format: compressed, and pg_restore can restore selectively.
    dump = runner(["pg_dump", "--format=custom", "--no-owner", "--no-acl"], _connection_env(db))
    if not dump:
        raise BackupError("pg_dump produced no output")
    # Dated key: a retry on the same day overwrites instead of piling up copies.
    return store.put(f"backups/tchekam-{now:%Y-%m-%d}.dump", dump, "application/octet-stream")
