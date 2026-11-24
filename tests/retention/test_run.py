"""The nightly run: one audit entry with counts, failure isolation, dry run, schedule."""

import logging
from datetime import timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command

from tchekam.core.models import AuditLog
from tchekam.messaging.models import InboundEvent
from tchekam.reports.models import Report
from tchekam.retention import rules
from tchekam.retention.run import run_retention

from .builders import NOW, event, report

pytestmark = pytest.mark.django_db

OLD = NOW - timedelta(days=60)


def test_each_run_writes_exactly_one_audit_entry_with_counts():
    event(OLD)
    event(OLD)
    report("draft", last_activity_at=OLD)

    result = run_retention(now=NOW)

    entry = AuditLog.objects.get(action="retention.run")
    assert entry.actor is None
    assert entry.metadata["counts"]["webhooks"] == 2
    assert entry.metadata["counts"]["drafts"] == 1
    assert set(entry.metadata["counts"]) == {rule.name for rule in rules.RULES}
    assert entry.metadata["errors"] == {}
    assert result.counts == entry.metadata["counts"]


def test_audit_entry_holds_no_personal_data():
    r = report("draft", last_activity_at=OLD)

    run_retention(now=NOW)

    text = str(AuditLog.objects.get(action="retention.run").metadata)
    assert r.reporter.wa_phone not in text and r.story_text not in text


def test_a_failing_rule_does_not_stop_the_others(monkeypatch, caplog):
    event(OLD)

    class Boom(Exception):
        pass

    def explode(now):
        raise Boom("+237670000001 secret detail")

    monkeypatch.setattr(rules.drafts, "candidates", explode)

    with caplog.at_level(logging.WARNING):
        result = run_retention(now=NOW)

    assert not InboundEvent.objects.exists()  # webhooks still ran
    entry = AuditLog.objects.get(action="retention.run")
    assert entry.metadata["errors"] == {"drafts": "Boom"}
    assert "drafts" not in entry.metadata["counts"]
    assert result.errors == {"drafts": "Boom"}
    assert "Boom" in caplog.text and "secret detail" not in caplog.text


def test_rules_process_in_batches(monkeypatch):
    monkeypatch.setattr(rules, "BATCH_SIZE", 2)
    for _ in range(5):
        event(OLD)

    assert rules.webhooks(NOW) == 5
    assert not InboundEvent.objects.exists()


def test_dry_run_counts_without_deleting_or_auditing():
    event(OLD)
    r = report("draft", last_activity_at=OLD)

    result = run_retention(now=NOW, dry_run=True)

    assert result.counts["webhooks"] == 1 and result.counts["drafts"] == 1
    assert InboundEvent.objects.exists() and Report.objects.filter(pk=r.pk).exists()
    assert not AuditLog.objects.filter(action="retention.run").exists()


def test_management_command_dry_run_prints_counts():
    event(NOW - timedelta(days=400))  # the command uses the real clock
    out = StringIO()

    call_command("run_retention", "--dry-run", stdout=out)

    assert "webhooks: 1" in out.getvalue()
    assert "dry run" in out.getvalue()
    assert InboundEvent.objects.exists()


def test_management_command_runs_and_audits():
    event(NOW - timedelta(days=400))
    out = StringIO()

    call_command("run_retention", stdout=out)

    assert "webhooks: 1" in out.getvalue()
    assert not InboundEvent.objects.exists()
    assert AuditLog.objects.filter(action="retention.run").count() == 1


def test_nightly_task_runs_at_two_in_douala():
    from procrastinate.contrib.django import app

    from tchekam.retention import tasks

    periodic = [
        p for p in app.periodic_registry.periodic_tasks.values() if p.task.name == "retention.run"
    ]
    assert len(periodic) == 1
    assert periodic[0].cron == "0 2 * * *"
    assert periodic[0].tzinfo == ZoneInfo("Africa/Douala")
    assert tasks.NIGHTLY_CRON == "0 2 * * *"


def test_nightly_task_runs_the_job_once():
    from tchekam.retention.tasks import nightly

    event(NOW - timedelta(days=400))

    nightly(timestamp=0)

    assert AuditLog.objects.filter(action="retention.run").count() == 1
