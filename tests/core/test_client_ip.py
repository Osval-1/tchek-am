from django.test import RequestFactory

from tchekam.core.http import client_ip


def ip(settings, count, xff=None, remote="10.0.0.1"):
    settings.TRUSTED_PROXY_COUNT = count
    extra = {"HTTP_X_FORWARDED_FOR": xff} if xff is not None else {}
    return client_ip(RequestFactory().get("/", REMOTE_ADDR=remote, **extra))


def test_zero_ignores_forwarded_for(settings):
    assert ip(settings, 0, "203.0.113.9") == "10.0.0.1"


def test_takes_the_rightmost_hop_so_a_forged_leading_entry_is_ignored(settings):
    assert ip(settings, 1, "6.6.6.6, 203.0.113.9") == "203.0.113.9"


def test_counts_n_hops_from_the_right(settings):
    assert ip(settings, 2, "6.6.6.6, 203.0.113.9, 10.9.9.9") == "203.0.113.9"


def test_fewer_hops_than_proxies_falls_back_to_remote_addr(settings):
    assert ip(settings, 2, "203.0.113.9") == "10.0.0.1"
    assert ip(settings, 1) == "10.0.0.1"


def test_invalid_value_falls_back_to_remote_addr(settings):
    assert ip(settings, 1, "6.6.6.6, not-an-ip") == "10.0.0.1"
    assert ip(settings, 0, remote="garbage") is None
