"""Reporter trust survives erasure (ADR-015): ReporterTrust feeds reputation through its hook."""

import pytest

from tchekam.reports.keys import reporter_key_for
from tchekam.reports.models import Report
from tchekam.reputation.service import band_for_phone
from tchekam.retention import trust
from tchekam.retention.models import ReporterTrust

from .builders import NOW, phone, report, user

pytestmark = pytest.mark.django_db


def test_deleting_a_reporter_stores_their_trust_first():
    low = user(trust_weight=0.2)
    report("rejected", low)
    key = reporter_key_for(low.wa_phone)

    low.delete()

    assert ReporterTrust.objects.get(reporter_key=key).trust_weight == 0.2


def test_deleting_someone_who_never_reported_stores_nothing():
    user(trust_weight=0.2).delete()

    assert not ReporterTrust.objects.exists()


def test_lookup_never_exceeds_the_snapshot():
    live = user(trust_weight=0.9)
    report("approved", live)
    key = reporter_key_for(live.wa_phone)
    ReporterTrust.objects.create(reporter_key=key, trust_weight=0.1)

    assert trust.trust_for_keys(frozenset({key, "unknown"})) == {key: 0.1}


def test_lookup_uses_live_trust_when_lower_or_alone():
    live = user(trust_weight=0.4)
    report("approved", live)
    key = reporter_key_for(live.wa_phone)
    assert trust.trust_for_keys(frozenset({key})) == {key: 0.4}

    ReporterTrust.objects.create(reporter_key=key, trust_weight=0.8)
    assert trust.trust_for_keys(frozenset({key})) == {key: 0.4}


def test_a_returning_number_starts_at_its_stored_trust():
    old = user(trust_weight=0.1)
    report("approved", old)
    number = old.wa_phone
    old.delete()

    back = user(wa_phone=number)

    assert back.trust_weight == 0.1
    back.refresh_from_db()
    assert back.trust_weight == 0.1


def test_a_returning_number_starts_at_the_weight_of_its_old_decisions():
    from tchekam.reports.weighting import trust_weight

    old = user()
    for _ in range(3):
        report("rejected", old)
    number = old.wa_phone
    Report.objects.filter(reporter=old).update(reporter=None)  # unlinked without a snapshot
    old.delete()
    from tchekam.retention.models import ReporterTrust as RT

    RT.objects.all().delete()

    back = user(wa_phone=number)

    assert back.trust_weight == trust_weight(0, 3)


def test_a_new_number_keeps_the_default_trust():
    assert user().trust_weight == 1.0


def _approved_with_proof(seller, reporter):
    from datetime import timedelta

    r = report("approved", reporter, seller=seller, has_payment_proof=True)
    Report.objects.filter(pk=r.pk).update(decided_at=NOW - timedelta(days=10))
    return r


def test_an_erased_low_trust_reporter_does_not_regain_full_weight():
    seller = phone()
    low = user(trust_weight=0.2)
    _approved_with_proof(seller, low)
    assert band_for_phone(seller.e164, now=NOW).band == "orange"

    low.delete()

    assert band_for_phone(seller.e164, now=NOW).band == "orange"


def test_an_erased_trusted_reporter_keeps_counting():
    seller = phone()
    good = user(trust_weight=0.9)
    _approved_with_proof(seller, good)
    assert band_for_phone(seller.e164, now=NOW).band == "red"

    good.delete()

    assert band_for_phone(seller.e164, now=NOW).band == "red"


def test_erasing_then_returning_never_makes_a_band_more_red():
    """R3/ADR-015 monotonicity across erase -> re-register -> new draft."""
    seller = phone()
    low = user(trust_weight=0.1)
    _approved_with_proof(seller, low)
    before = band_for_phone(seller.e164, now=NOW).band
    number = low.wa_phone

    low.delete()
    after_erase = band_for_phone(seller.e164, now=NOW).band
    back = user(wa_phone=number)
    Report.objects.create(reporter=back, status="draft")
    after_return = band_for_phone(seller.e164, now=NOW).band

    assert before == after_erase == after_return == "orange"


# The snapshot only ever goes down (reviewer scenarios, ISSUES.md Issue 24) ---------------------

NUM = "+237670099001"


def _band(e164):
    from django.core.cache import cache

    cache.clear()
    return band_for_phone(e164, now=NOW).band


def _low_reporter_with_proof(seller, number=NUM):
    """1 approved report with payment proof and 5 rejections: trust 0.25, band orange."""
    from tchekam.reports.weighting import recompute

    a = user(wa_phone=number)
    _approved_with_proof(seller, a)
    for _ in range(5):
        report("rejected", a)
    recompute(a)
    a.refresh_from_db()
    assert a.trust_weight == 0.25
    return a


def _approve_more(account, n=5):
    from tchekam.reports.weighting import recompute

    for _ in range(n):
        report("approved", account)
    recompute(account)
    account.refresh_from_db()


def test_snapshot_is_never_raised():
    low = user(trust_weight=0.25)
    report("approved", low)
    trust.snapshot(low)
    low.trust_weight = 0.9

    trust.snapshot(low)

    assert ReporterTrust.objects.get().trust_weight == 0.25
    low.trust_weight = 0.1
    trust.snapshot(low)
    assert ReporterTrust.objects.get().trust_weight == 0.1


@pytest.mark.parametrize("who", ["same person", "recycled number"])
def test_a_later_account_on_the_number_cannot_raise_old_reports(who):
    from tchekam.conversations.models import BotUser

    seller = phone()
    first = _low_reporter_with_proof(seller)
    assert _band(seller.e164) == "orange"
    first.delete()
    assert _band(seller.e164) == "orange"

    # The same person back, or an operator gives the number to someone else: either way the
    # new account's own decisions raise its trust above the old snapshot.
    later, _ = BotUser.objects.get_or_create(wa_phone=NUM)
    if who == "recycled number":
        later.language = "fr"  # a different owner; nothing links them but the number
        later.save(update_fields=["language"])
    _approve_more(later)
    assert later.trust_weight > 0.25
    before = _band(seller.e164)

    later.delete()

    assert before == _band(seller.e164) == "orange"
    assert ReporterTrust.objects.get(reporter_key=reporter_key_for(NUM)).trust_weight == 0.25


def test_anonymisation_never_raises_the_snapshot(django_capture_on_commit_callbacks):
    from datetime import timedelta

    from tchekam.conversations.models import BotUser
    from tchekam.retention import rules

    seller = phone()
    _low_reporter_with_proof(seller).delete()
    back, _ = BotUser.objects.get_or_create(wa_phone=NUM)
    old = report("approved", back)
    Report.objects.filter(pk=old.pk).update(decided_at=NOW - timedelta(days=4 * 365))
    _approve_more(back)
    before = _band(seller.e164)

    with django_capture_on_commit_callbacks(execute=True):
        assert rules.approved_evidence(NOW) == 1

    assert before == _band(seller.e164) == "orange"
    assert ReporterTrust.objects.get(reporter_key=reporter_key_for(NUM)).trust_weight == 0.25
