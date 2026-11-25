"""Evaluation runner: `uv run python -m evals.run extraction`.

Calls the real model, so it runs only with AI_BACKEND=openrouter and an OPENROUTER_API_KEY set;
otherwise it prints a skip message and exits 0. It is not part of the pytest run.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "evals" / "extraction" / "cases"
SCORED_FIELDS = ("phone_numbers", "account_names", "amounts_xaf")
_PLACEHOLDER_KEYS = {"", "changeme"}


def field_scores(predicted: list, expected: list) -> tuple[int, int, int]:
    """(true positives, false positives, false negatives), comparing as sets."""
    got, want = set(predicted), set(expected)
    return len(got & want), len(got - want), len(want - got)


def _setup_django() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tchekam.settings.dev")
    import django

    django.setup()


def _ratio(num: int, den: int) -> str:
    return f"{num / den:.2f}" if den else "n/a"


def run_extraction() -> int:
    from tchekam.ai.extraction import extract_evidence
    from tchekam.identifiers.names import normalize_name

    totals = {field: [0, 0, 0] for field in SCORED_FIELDS}
    number_hits = failures = 0
    cases = sorted(CASES_DIR.glob("*.json"))
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        images = [((path.parent / p).resolve().read_bytes(), "image/png") for p in case["images"]]
        result = extract_evidence(images, case.get("transcript"), case.get("story"), case["lang"])
        expected = case["expected"]
        predicted = {
            "phone_numbers": result.phone_numbers,
            "account_names": [normalize_name(a.name) for a in result.account_names],
            "amounts_xaf": result.amounts_xaf,
        }
        wanted = {
            **expected,
            "account_names": [normalize_name(n) for n in expected["account_names"]],
        }
        for field in SCORED_FIELDS:
            for i, value in enumerate(field_scores(predicted[field], wanted[field])):
                totals[field][i] += value
        # Reported number is right when the expected seller number is among those extracted.
        hit = expected["reported_number"] in result.phone_numbers
        number_hits += hit
        failures += result.extraction_failed
        status = "FAILED" if result.extraction_failed else ("ok" if hit else "MISSED NUMBER")
        print(f"{path.stem:<24} {status}")

    print()
    print(f"{'field':<16}{'tp':>5}{'fp':>5}{'fn':>5}{'precision':>11}{'recall':>8}")
    for field, (tp, fp, fn) in totals.items():
        print(f"{field:<16}{tp:>5}{fp:>5}{fn:>5}{_ratio(tp, tp + fp):>11}{_ratio(tp, tp + fn):>8}")
    print()
    print(
        f"reported-number accuracy: {_ratio(number_hits, len(cases))} ({number_hits}/{len(cases)})"
    )
    print(f"extraction failures: {failures}/{len(cases)}")
    return 0


SUITES = {"extraction": run_extraction}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in SUITES:
        print(f"usage: python -m evals.run {{{','.join(SUITES)}}}")
        return 2
    _setup_django()
    from django.conf import settings

    if settings.AI_BACKEND != "openrouter" or settings.OPENROUTER_API_KEY in _PLACEHOLDER_KEYS:
        print(
            "Skipping evals: set AI_BACKEND=openrouter and a real OPENROUTER_API_KEY to run them."
        )
        return 0
    return SUITES[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
