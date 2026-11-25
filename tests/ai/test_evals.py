import json

import pytest
from evals import run
from evals.run import CASES_DIR, field_scores

from tchekam.identifiers.phone import normalize_cm_number


def test_runner_skips_cleanly_without_a_key(settings, capsys):
    settings.OPENROUTER_API_KEY = ""
    settings.AI_BACKEND = "openrouter"

    assert run.main(["extraction"]) == 0
    assert "skip" in capsys.readouterr().out.lower()


def test_runner_skips_on_the_fake_backend(settings, capsys):
    settings.OPENROUTER_API_KEY = "sk-something"
    settings.AI_BACKEND = "fake"

    assert run.main(["extraction"]) == 0
    assert "skip" in capsys.readouterr().out.lower()


def test_unknown_suite_is_an_error(capsys):
    assert run.main(["nope"]) == 2


def test_field_scores_precision_and_recall():
    assert field_scores(["a", "b"], ["a", "c", "d"]) == (1, 1, 2)  # tp, fp, fn


@pytest.mark.parametrize("path", sorted(CASES_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_cases_reference_committed_images(path):
    case = json.loads(path.read_text(encoding="utf-8"))

    assert case["note"]
    assert set(case["expected"]) >= {"phone_numbers", "account_names", "amounts_xaf"}
    assert case["expected"]["reported_number"]
    for number in [*case["expected"]["phone_numbers"], case["expected"]["reported_number"]]:
        assert normalize_cm_number(number) == number
    for image in case["images"]:
        assert (path.parent / image).resolve().is_file(), image


def test_five_cases_ship():
    assert len(list(CASES_DIR.glob("*.json"))) == 5
