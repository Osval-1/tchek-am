import logging

import pytest


@pytest.mark.parametrize("name", ["httpx", "httpx2", "httpcore"])
def test_http_client_loggers_do_not_emit_request_urls_at_info(name):
    assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
