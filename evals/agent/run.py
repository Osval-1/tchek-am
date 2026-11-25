"""Opt-in synthetic evaluation. Contract success is never live-model release evidence.

Run `uv run python -m evals.agent.run --target contracts` for network-free tests.
Live inference requires --target live --budget-usd <finite limit> and an approved
chat policy. It uses a uniquely named temporary PostgreSQL database, FakeChannel,
and synthetic actors only. No existing database is migrated or used for fixtures.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from importlib.metadata import version
from math import ceil
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).with_name("cases.json")
GATES = {
    "task_success_min": 0.90,
    "safety_violations_max": 0,
    "p95_seconds_max": 60,
    "mean_reserved_usd_max": 0.05,
}


def nearest_rank_p95(values):
    if not values:
        raise ValueError("No processing measurements")
    ordered = sorted(values)
    return ordered[ceil(0.95 * len(ordered)) - 1]


def validate_cases(cases):
    """Reject malformed or ambiguous development fixtures before invoking a model."""
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset must contain at least one case")
    ids = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each case must be an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in ids:
            raise ValueError("Case ids must be nonempty and unique")
        ids.add(case_id)
        if case.get("lang") not in {"fr", "en", "pcm"}:
            raise ValueError(f"Invalid language for {case_id}")
        if not isinstance(case.get("input"), str) or not case["input"].strip():
            raise ValueError(f"Missing input for {case_id}")
    return cases


def implementation_digest():
    """Include new source files: git diff alone omits this uncommitted feature."""
    paths = [*ROOT.joinpath("src").rglob("*.py"), *ROOT.joinpath("evals/agent").glob("*.py")]
    paths += list(ROOT.joinpath("src/tchekam/ai/prompts/agent").glob("*.md"))
    paths += [ROOT / "pyproject.toml", ROOT / "uv.lock"]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def live(budget_usd, *, case_limit=None, collection="dialogue", case_ids=None):
    from time import monotonic

    sys.path.insert(0, str(ROOT / "src"))
    os.environ["DJANGO_SETTINGS_MODULE"] = "tchekam.settings.test"
    os.environ["LANGSMITH_TRACING"] = "false"
    import django

    django.setup()
    from django.conf import settings
    from django.db.models import Sum
    from django.test.utils import setup_databases, teardown_databases

    from tchekam.ai.agent.execution import claim
    from tchekam.ai.agent.graph import build_graph
    from tchekam.ai.agent.policy import role_policy
    from tchekam.ai.agent.tracing import local_synthetic_tracer
    from tchekam.ai.models import (
        AgentControl,
        AgentOperation,
        AgentReservation,
        AgentRun,
        AICallLog,
    )
    from tchekam.conversations.models import BotUser, Conversation
    from tchekam.messaging.models import InboundEvent

    role_policy("chat")  # fail before creating even a temporary database if ineligible
    settings.AGENT_ENABLED = True
    settings.AGENT_VISION_ENABLED = collection == "vision"
    settings.AGENT_LANGUAGES = ["fr", "en", "pcm"]
    settings.AGENT_MEMORY_KEYS = {"synthetic": uuid4().hex}
    settings.AGENT_MEMORY_KEY_VERSION = "synthetic"
    settings.AGENT_OPERATION_KEY = uuid4().hex
    settings.AGENT_DAILY_BUDGET_MICROUSD = int(budget_usd * 1_000_000)
    settings.AGENT_MONTHLY_BUDGET_MICROUSD = int(budget_usd * 1_000_000)
    settings.DATABASES["default"]["TEST"]["NAME"] = "agent_eval_" + uuid4().hex[:16]
    old = setup_databases(verbosity=0, interactive=False, keepdb=False)
    results = []
    try:
        control = AgentControl.objects.create(
            pk=1, enabled=True, rollout_percentage=100, vision_enabled=collection == "vision"
        )
        if collection == "vision":
            from evals.agent.vision_fixtures import ASSETS, generate
            from evals.agent.vision_fixtures import cases as vision_cases
            from tchekam.messaging.fake import FakeChannel

            generate()
            cases = vision_cases()
        else:
            cases = json.loads(CASES.read_text(encoding="utf-8"))
        validate_cases(cases)
        if case_ids:
            cases = [case for case in cases if case["id"] in case_ids]
            if {case["id"] for case in cases} != set(case_ids):
                raise ValueError("Unknown case id")
        if case_limit is not None:
            cases = cases[:case_limit]
        if not cases:
            raise ValueError("No cases selected")
        for i, case in enumerate(cases, 1):
            user = BotUser.objects.create(wa_phone=f"+2376900{i:05d}", language=case["lang"])
            Conversation.objects.create(user=user, agent_sequence=1)
            control.pilot_users.add(user)
            key = f"synthetic-{i}"
            if case.get("kind") == "image":
                message = {"imageMessage": {"caption": case["input"], "mimetype": "image/png"}}
                FakeChannel.instance().media[key] = (
                    (ASSETS / case["asset"]).read_bytes(),
                    "image/png",
                )
            else:
                message = {"conversation": case["input"]}
            event = InboundEvent.objects.create(
                message_id=key,
                event="messages.upsert",
                payload={
                    "event": "messages.upsert",
                    "data": {
                        "key": {
                            "id": key,
                            "remoteJid": user.wa_phone.lstrip("+") + "@s.whatsapp.net",
                            "fromMe": False,
                        },
                        "message": message,
                    },
                },
            )
            run = AgentRun.objects.create(
                user=user, inbound=event, inbound_key=key, generation=0, sequence=1
            )
            ctx = claim(run.pk)
            ctx.tracer = local_synthetic_tracer()
            started = monotonic()
            state = build_graph(ctx).invoke({"run_id": run.pk})
            elapsed = monotonic() - started
            ctx.tracer.flush()
            tools = set(
                AgentOperation.objects.filter(run=run, outcome="allowed").values_list(
                    "tool", flat=True
                )
            )
            action = state.get("action")
            passed = bool(state.get("completed")) and state.get("outcome") != "fallback"
            if case.get("tool"):
                expected = case["tool"]
                passed &= tools == {expected}
                # Calling the right tool is insufficient if its result is then dropped.
                passed &= action is not None and any(
                    ctx.results[handle].operation == expected
                    for handle in action.handles
                    if handle in ctx.results
                )
            if case.get("clarify"):
                passed &= action is not None and action.kind == "clarify"
            if case.get("advice"):
                passed &= action is not None and (
                    action.kind == "advice" or "what_to_do_next" in tools
                )
            if case.get("no_tools"):
                passed &= not tools
            if case.get("expected_values"):
                text = "\n".join(state.get("replies", []))
                passed &= all(value in text for value in case["expected_values"])
            charged = AgentReservation.objects.filter(run=run).aggregate(n=Sum("amount"))["n"] or 0
            results.append(
                {
                    "id": case["id"],
                    "passed": passed,
                    "seconds": elapsed,
                    "reserved_microusd": charged,
                    "reservations": list(
                        AgentReservation.objects.filter(run=run).values("status", "amount")
                    ),
                    "tools": sorted(tools),
                    "trusted_results": [
                        {"tool": result.operation, "texts": list(result.texts)}
                        for result in ctx.results.values()
                    ],
                    "action": action.model_dump() if action else None,
                    "replies": state.get("replies", []),
                    "outcome": state.get("outcome", "ok"),
                    "denial_code": ctx.denial_code,
                    "proposed_action": ctx.proposed_action.model_dump()
                    if ctx.proposed_action
                    else None,
                    "result_handles": list(ctx.results),
                    "calls": list(
                        AICallLog.objects.filter(agent_run=run).values(
                            "purpose",
                            "model",
                            "request_id",
                            "serving_provider",
                            "success",
                            "error",
                            "tokens_in",
                            "tokens_out",
                            "latency_ms",
                        )
                    ),
                }
            )
            print(
                f"{case['id']}: {'PASS' if passed else 'FAIL'} ({elapsed:.2f}s, "
                f"reserved ${charged / 1_000_000:.6f})",
                flush=True,
            )
        local_synthetic_tracer().flush()
    finally:
        teardown_databases(old, verbosity=0)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["contracts", "live"], required=True)
    parser.add_argument("--budget-usd", type=Decimal)
    parser.add_argument("--case-limit", type=int)
    parser.add_argument("--collection", choices=["dialogue", "vision"], default="dialogue")
    parser.add_argument(
        "--case-ids", help="Comma-separated case ids; expected labels are never sent to the model"
    )
    parser.add_argument("--output", type=Path, default=ROOT / ".scratch/agent-evaluation.json")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Evaluation receipt already exists; choose a new --output to preserve history")
    if args.case_limit is not None and args.case_limit <= 0:
        parser.error("--case-limit must be positive")
    if args.target == "live" and (
        args.budget_usd is None or not args.budget_usd.is_finite() or args.budget_usd <= 0
    ):
        parser.error("Live inference requires an explicit positive finite --budget-usd")
    dataset = CASES.read_bytes()
    if args.collection == "vision":
        from evals.agent.vision_fixtures import cases as vision_cases
        from evals.agent.vision_fixtures import generate

        dataset = json.dumps(
            {"cases": vision_cases(), "assets": generate()}, sort_keys=True
        ).encode()
    report = {
        "target": args.target,
        "collection": args.collection,
        "dataset_sha256": hashlib.sha256(dataset).hexdigest(),
        "implementation_sha256": implementation_digest(),
        "gates": GATES,
        "release_ready": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "layer": "L0-L2" if args.target == "contracts" else "L3-smoke",
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip(),
        "worktree_diff_sha256": hashlib.sha256(
            subprocess.run(
                ["git", "diff", "--binary"], cwd=ROOT, capture_output=True, check=True
            ).stdout
        ).hexdigest(),
        "prompt_version": "agent-v1",
        "policy_version": "agent-v1",
        "role_policies": {
            role: {
                name: policy[name]
                for name in ("models", "endpoints", "max_cost_microusd", "reasoning", "temperature")
                if name in policy
            }
            for role, policy in json.loads(os.environ.get("AGENT_ROLE_POLICIES", "{}")).items()
        },
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256(
            (ROOT / "src/tchekam/ai/prompts/agent/v1.md").read_bytes()
        ).hexdigest(),
        "catalog_sha256": hashlib.sha256(
            (ROOT / "src/tchekam/i18n/catalog_agent.py").read_bytes()
        ).hexdigest(),
        "packages": {
            p: version(p) for p in ("langchain", "langgraph", "langchain-openrouter", "langfuse")
        },
    }
    if args.target == "contracts":
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/ai/agent", "-q"], cwd=ROOT, check=False
        )
        report["contracts_passed"] = result.returncode == 0
        code = result.returncode
    else:
        try:
            results = live(
                args.budget_usd,
                case_limit=args.case_limit,
                collection=args.collection,
                case_ids=args.case_ids.split(",") if args.case_ids else None,
            )
            report["results"] = results
            report["task_success"] = sum(r["passed"] for r in results) / len(results)
            report["budget_usd"] = str(args.budget_usd)
            report["charged_or_reserved_usd"] = (
                sum(r["reserved_microusd"] for r in results) / 1_000_000
            )
            report["p95_seconds"] = nearest_rank_p95([r["seconds"] for r in results])
            report["percentile_method"] = "nearest_rank"
            report["mean_reserved_usd"] = (
                sum(r["reserved_microusd"] for r in results) / len(results) / 1_000_000
            )
            report["smoke_passed"] = (
                report["task_success"] >= GATES["task_success_min"]
                and report["p95_seconds"] <= GATES["p95_seconds_max"]
                and report["mean_reserved_usd"] <= GATES["mean_reserved_usd_max"]
            )
            report["safety_gate_status"] = (
                "incomplete: independent safety observations not captured"
            )
            code = 0 if report["smoke_passed"] else 1
        except Exception as exc:
            import traceback

            report.update(
                status="incomplete",
                error_type=type(exc).__name__,
                error_locations=[
                    {
                        "file": Path(frame.filename).name,
                        "function": frame.name,
                        "line": frame.lineno,
                    }
                    for frame in traceback.extract_tb(exc.__traceback__)
                ],
            )
            code = 2
    # This development smoke cannot establish the larger held-out release evidence.
    report["remaining_gates"] = [
        "full_adversarial",
        "multi_worker_performance",
        "role_quality_and_native_review",
        "real_world_media",
        "production_configuration_and_processor_inventory",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Evaluation receipt: {args.output}; release_ready=false")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
