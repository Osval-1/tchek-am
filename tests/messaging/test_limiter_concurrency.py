"""Races that need real transactions on separate connections."""

import threading

import pytest
from django.db import connection

from tchekam.messaging import limiter
from tchekam.messaging.channel import Deferred
from tchekam.messaging.models import RecipientSend


def _run_threads(count, recipients):
    results = []

    def attempt(to):
        try:
            limiter.acquire(to)
            results.append("ok")
        except Deferred:
            results.append("deferred")
        except Exception as exc:  # noqa: BLE001
            results.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(recipients(i),)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


@pytest.mark.django_db(transaction=True)
def test_concurrent_sends_to_one_recipient_respect_the_per_recipient_limit(settings):
    settings.SEND_RATE_PER_MINUTE = 1000

    results = _run_threads(10, lambda i: "237670000001")

    assert results.count("ok") == limiter.RECIPIENT_MAX_SENDS == 6
    assert results.count("deferred") == 4
    assert RecipientSend.objects.count() == 6


@pytest.mark.django_db(transaction=True)
def test_concurrent_sends_respect_the_global_bucket(settings):
    settings.SEND_RATE_PER_MINUTE = 3

    results = _run_threads(8, lambda i: f"2376700000{i:02d}")

    assert results.count("ok") == 3
    assert results.count("deferred") == 5
    assert RecipientSend.objects.count() == 3
