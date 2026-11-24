import logging
import subprocess
from datetime import UTC, datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tchekam.core import backup
from tchekam.core.storage import InMemoryObjectStore

NOW = datetime(2026, 12, 1, 3, 0, tzinfo=UTC)
DB = {
    "NAME": "tchekam",
    "USER": "u",
    "PASSWORD": "hunter2",
    "HOST": "db.internal",
    "PORT": "5432",
}


class FakeRunner:
    def __init__(self, output=b"PGDMP-data"):
        self.output = output
        self.calls = []

    def __call__(self, args, env):
        self.calls.append((args, env))
        return self.output


def test_backup_uploads_the_dump_under_a_dated_key():
    store, runner = InMemoryObjectStore(), FakeRunner()

    key = backup.create_backup(store, now=NOW, runner=runner, db=DB)

    assert key == "backups/tchekam-2026-12-01.dump"
    assert store.get(key) == b"PGDMP-data"


def test_backup_passes_the_password_by_environment_never_by_argument():
    runner = FakeRunner()

    backup.create_backup(InMemoryObjectStore(), now=NOW, runner=runner, db=DB)

    ((args, env),) = runner.calls
    assert args[0] == "pg_dump" and "--format=custom" in args
    assert "hunter2" not in " ".join(args)
    assert env == {
        "PGHOST": "db.internal",
        "PGPORT": "5432",
        "PGUSER": "u",
        "PGPASSWORD": "hunter2",
        "PGDATABASE": "tchekam",
    }


def test_backup_defaults_to_the_configured_database_and_store(settings):
    runner = FakeRunner()

    backup.create_backup(InMemoryObjectStore(), now=NOW, runner=runner)

    assert runner.calls[0][1]["PGDATABASE"] == settings.DATABASES["default"]["NAME"]


def test_an_empty_dump_is_not_uploaded():
    store = InMemoryObjectStore()

    with pytest.raises(backup.BackupError):
        backup.create_backup(store, now=NOW, runner=FakeRunner(b""), db=DB)

    assert not store.exists("backups/tchekam-2026-12-01.dump")


def test_pg_dump_runner_returns_stdout(monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs, args=args)
        return subprocess.CompletedProcess(args, 0, stdout=b"dump", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert backup.pg_dump_runner(["pg_dump"], {"PGPASSWORD": "p"}) == b"dump"
    assert seen["env"]["PGPASSWORD"] == "p" and seen["check"] is False


def test_pg_dump_failure_raises_without_leaking_output(monkeypatch, caplog):
    def fake_run(args, **kwargs):
        stderr = b"pg_dump: error: contact +237677123456"
        return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with caplog.at_level(logging.ERROR), pytest.raises(backup.BackupError) as exc:
        backup.pg_dump_runner(["pg_dump"], {})

    assert "status 1" in str(exc.value)
    assert "677123456" not in caplog.text


def test_pg_dump_missing_binary_is_a_backup_error(monkeypatch):
    def fake_run(args, **kwargs):
        raise FileNotFoundError("pg_dump")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(backup.BackupError):
        backup.pg_dump_runner(["pg_dump"], {})


def test_command_reports_the_key(monkeypatch):
    monkeypatch.setattr(backup, "pg_dump_runner", FakeRunner())
    out = StringIO()

    call_command("backup_database", stdout=out)

    assert "backups/tchekam-" in out.getvalue()


def test_command_turns_failure_into_a_command_error(monkeypatch):
    monkeypatch.setattr(backup, "pg_dump_runner", FakeRunner(b""))

    with pytest.raises(CommandError):
        call_command("backup_database")


def test_monthly_task_is_registered_and_runs(monkeypatch):
    from procrastinate.contrib.django import app

    from tchekam.core import tasks

    runner = FakeRunner()
    monkeypatch.setattr(backup, "pg_dump_runner", runner)

    periodic = [p for p in app.periodic_registry.periodic_tasks.values()]
    task = next(p for p in periodic if p.task.name == "core.backup_database")
    assert task.cron == "0 3 1 * *"

    tasks._REGISTRY["core.backup_database"](timestamp=0)

    assert len(runner.calls) == 1
