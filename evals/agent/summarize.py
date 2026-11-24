"""Archive synthetic live receipts and account conservatively for the owner's $1 test."""

import json
from decimal import Decimal
from pathlib import Path

from .run import nearest_rank_p95

ROOT = Path(__file__).resolve().parents[2]


def main():
    output = ROOT / "evals/agent/results/2026-11-24-initial"
    output.mkdir(parents=True, exist_ok=True)
    trials, total = [], 0
    for path in sorted((ROOT / ".scratch").glob("agent-live-*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("target") != "live" or "results" not in report:
            continue
        destination = output / path.name
        if destination.exists() and json.loads(destination.read_text(encoding="utf-8")) != report:
            raise RuntimeError(f"Refusing to replace a different archived receipt: {path.name}")
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        rows = report["results"]
        charged = sum(row["reserved_microusd"] for row in rows)
        total += charged
        trials.append(
            {
                "receipt": path.name,
                "collection": report.get(
                    "collection", "vision" if "vision" in path.name else "dialogue"
                ),
                "cases": len(rows),
                "passed": sum(row["passed"] for row in rows),
                "p95_seconds_nearest_rank": nearest_rank_p95([row["seconds"] for row in rows]),
                "charged_or_reserved_microusd": charged,
                "failed_cases": [row["id"] for row in rows if not row["passed"]],
            }
        )
    # The first probe lost settlement/audit during the SDK cleanup bug. Its three
    # 30,000-micro-USD reservations remain fully held; never assume those calls were free.
    initial = next(trial for trial in trials if trial["receipt"] == "agent-live-probe.json")
    unknown = initial["charged_or_reserved_microusd"]
    if total > 1_000_000:
        raise RuntimeError("Initial synthetic-test ceiling exceeded")
    summary = {
        "synthetic_only": True,
        "authorized_usd": "1.00",
        "model": "deepseek/deepseek-v4.1-flash-1017",
        "serving_endpoint": "together/us",
        "zdr_confirmation": (
            "Owner confirmed enabled on all AI models; requests retain strict ZDR routing."
        ),
        "known_reported_charges_usd": str(Decimal(total - unknown) / 1_000_000),
        "uncertain_charge_reservations_usd": str(Decimal(unknown) / 1_000_000),
        "conservative_accounted_usd": str(Decimal(total) / 1_000_000),
        "unused_authorized_ceiling_usd": str(Decimal(1_000_000 - total) / 1_000_000),
        "latest_dialogue": "agent-live-dialogue-release-smoke.json",
        "latest_vision": "agent-live-vision-verified.json",
        "unique_dialogue_cases": 33,
        "unique_image_cases": 3,
        "note": (
            "Trials are repeated development cases, not independent held-out release evidence. "
            "All earlier failures are preserved."
        ),
        "trials": trials,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    policy = json.loads((ROOT / ".scratch/agent-live-policies.json").read_text(encoding="utf-8"))
    (output / "policy-tested.json").write_text(
        json.dumps(policy, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "known_reported_charges_usd",
                    "uncertain_charge_reservations_usd",
                    "conservative_accounted_usd",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
