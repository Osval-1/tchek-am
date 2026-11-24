"""Lightweight checks of render.yaml: Render publishes no offline schema validator.

Manual check (documented in docs/runbook.md): in the Render dashboard choose New > Blueprint
and point it at the repo; the page lists every problem before anything is created.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))


def _service(kind):
    (service,) = [s for s in BLUEPRINT["services"] if s["type"] == kind]
    return service


def _env_keys(service):
    group_names = [e["fromGroup"] for e in service["envVars"] if "fromGroup" in e]
    groups = {g["name"]: g for g in BLUEPRINT.get("envVarGroups", [])}
    keys = {e["key"] for e in service["envVars"] if "key" in e}
    for name in group_names:
        keys |= {e["key"] for e in groups[name]["envVars"]}
    return keys


def test_everything_runs_in_frankfurt():
    assert _service("web")["region"] == "frankfurt"
    assert _service("worker")["region"] == "frankfurt"
    (database,) = BLUEPRINT["databases"]
    assert database["region"] == "frankfurt"


def test_web_service_uses_the_image_health_check_and_migrates_before_deploy():
    web = _service("web")

    assert web["runtime"] == "docker"
    assert web["healthCheckPath"] == "/healthz"
    assert "manage.py migrate" in web["preDeployCommand"]


def test_worker_serves_both_queues_with_the_runbook_concurrency():
    worker = _service("worker")

    assert worker["runtime"] == "docker"
    command = worker["dockerCommand"]
    assert "procrastinate worker" in command
    assert "-q default,whatsapp" in command
    assert "--concurrency 8" in command


def test_database_url_comes_from_the_blueprint_database():
    (database,) = BLUEPRINT["databases"]
    for kind in ("web", "worker"):
        (var,) = [e for e in _service(kind)["envVars"] if e.get("key") == "DATABASE_URL"]
        assert var["fromDatabase"]["name"] == database["name"]


def test_proxy_count_and_sse_are_set_for_render():
    values = {
        e["key"]: e.get("value")
        for g in BLUEPRINT["envVarGroups"]
        for e in g["envVars"]
        if "key" in e
    }
    assert values["TRUSTED_PROXY_COUNT"] == "1"
    assert values["S3_SSE"] == "true"
    assert values["DJANGO_SETTINGS_MODULE"] == "tchekam.settings.prod"


@pytest.mark.parametrize("kind", ["web", "worker"])
def test_every_variable_prod_settings_requires_is_declared(kind):
    prod = (ROOT / "src/tchekam/settings/prod.py").read_text(encoding="utf-8")
    # env("NAME") / env.list("NAME") with no default= are the ones prod refuses to start without.
    required = set(re.findall(r'env(?:\.\w+)?\("([A-Z0-9_]+)"\)', prod))

    assert required  # guards the regex itself
    assert required <= _env_keys(_service(kind))


def test_secrets_are_never_given_a_value_in_the_file():
    for service in BLUEPRINT["services"]:
        for var in service["envVars"]:
            if var.get("sync") is False:
                assert "value" not in var
    secret_like = re.compile(r"(KEY|SECRET|DSN|TOKEN)")
    for group in BLUEPRINT["envVarGroups"]:
        for var in group["envVars"]:
            # Only a generated value may stand in a group for a secret.
            if secret_like.search(var["key"]):
                assert var.get("generateValue") is True


def test_web_and_worker_declare_the_same_secrets():
    def secrets(kind):
        return {e["key"] for e in _service(kind)["envVars"] if e.get("sync") is False}

    assert secrets("web") == secrets("worker")
    assert "REPORTER_KEY_SECRET" in secrets("web")
