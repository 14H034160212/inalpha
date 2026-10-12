"""Development runner boundaries: paired failures, frozen evidence, retries and spend."""

import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from inalpha_research.pilot.artifacts import PilotArtifacts, validate_materials
from inalpha_research.pilot.campaign import campaign
from inalpha_research.pilot.experiment import (
    AttemptRunner,
    BudgetStop,
    CampaignBudget,
    recorder_for,
    validate_decision,
)
from inalpha_research.pilot.materials import build_materials
from inalpha_research.pilot.report import build_report, intervention_plans

CONFIG = {
    "provider": "deepseek",
    "model": "deepseek-flash",
    "limit_usd": "5",
    "baseline_tokens": 4000,
    "arm_tokens": 24000,
    "units": 2,
    "rounds": 2,
    "pricing": {
        "currency": "USD",
        "version": "fixture",
        "input_usd_per_million": "0.3",
        "output_usd_per_million": "1.2",
    },
}


class Store:
    def __init__(self):
        self.starts = []
        self.ends = []

    async def begin(self, *args):
        self.starts.append(args)

    async def settle(self, *args):
        self.ends.append(args)


def market():
    dates = [
        (datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i)).date().isoformat()
        for i in range(300)
    ]
    rows = [
        {
            "session": s,
            "open": 100 + i / 10,
            "close": 100.5 + i / 10,
            "low": 99 + i / 10,
            "high": 102 + i / 10,
            "volume": 1000 + i,
        }
        for i, s in enumerate(dates)
    ]
    return {
        "sessions": dates,
        "asset": rows,
        "benchmark": copy.deepcopy(rows),
        "source": "synthetic only",
        "session_closes": {s: s + "T20:00:00Z" for s in dates},
    }


def materials():
    source = market()
    return build_materials(source, source["sessions"][260:270])


def decision(ids=None):
    return {
        "p_up": 0.6,
        "p_flat": 0.3,
        "p_down": 0.1,
        "action": 1,
        "cited_evidence_ids": ["returns"] if ids is None else ids,
        "rationale": "fixture assessment",
    }


def response(value=None, usage=True, finish="stop"):
    return NS(
        choices=[NS(finish_reason=finish, message=NS(content=json.dumps(value or decision())))],
        model="fixture",
        usage=NS(prompt_tokens=100, completion_tokens=100) if usage else None,
    )


def test_materials_alignment_and_future_isolation():
    source = market()
    cases = source["sessions"][260:270]
    before = build_materials(source, cases)
    changed = copy.deepcopy(source)
    changed["asset"][280]["open"] *= 1.01
    after = build_materials(changed, cases)
    assert before["protocol"]["tau"] == after["protocol"]["tau"]
    assert [e["content"] for e in before["development"][0]["evidence"]] == [
        e["content"] for e in after["development"][0]["evidence"]
    ]
    assert not validate_materials(before)
    source["benchmark"].pop()
    with pytest.raises(ValueError, match="sessions"):
        build_materials(source, cases)


@pytest.mark.parametrize(
    "patch",
    [
        {"p_up": float("nan")},
        {"p_up": -0.1},
        {"p_flat": 0.9},
        {"action": True},
        {"cited_evidence_ids": ["future"]},
    ],
)
def test_invalid_outputs(patch):
    with pytest.raises(ValueError):
        validate_decision({**decision(), **patch}, {"returns"})


async def test_complete_four_arm_campaign_and_replays(tmp_path):
    data = materials()
    captured = []
    store = Store()

    async def invoke(**kwargs):
        payload = json.loads(kwargs["user"])
        captured.append(payload)
        return response(decision([payload["evidence"][0]["id"]]))

    result = await campaign(
        {"protocol": data["protocol"], "cases": data["development"][:1]},
        tmp_path / "campaign",
        CONFIG,
        store,
        "test:owner",
        invoke,
    )
    assert len(result["runs"]) == 4
    assert all(r["status"] == "completed" and not r["artifact_validation"] for r in result["runs"])
    d = result["runs"][-1]
    assert d["completed_units"] == 6
    assert len(store.starts) == len(store.ends)
    assert all(
        "TSLA" not in json.dumps(p)
        and "2024-" not in json.dumps(p)
        and '"excess_return":' not in json.dumps(p)
        for p in captured
    )
    report = build_report(result["runs"], data["labels"][:1], result["replays"])
    assert report["complete_case_count"] == 1
    assert {r["name"] for r in report["interventions"]} >= {
        "flip_conclusion",
        "delete_contribution",
        "remove_evidence",
        "downstream_noise",
    }
    plans = intervention_plans(d, data["development"][0])
    assert next(p for p in plans if p["name"] == "delete_contribution")["prefix"][-1]["removed"]
    assert d["history"][3]["output"] == decision() | {"action_probability_violation": False}


async def test_unknown_usage_stops_entire_campaign_and_keeps_all_cases(tmp_path):
    data = materials()
    calls = 0

    async def invoke(**kwargs):
        nonlocal calls
        calls += 1
        return response(usage=False)

    result = await campaign(
        {"protocol": data["protocol"], "cases": data["development"][:2]},
        tmp_path / "unknown",
        CONFIG,
        Store(),
        "test:owner",
        invoke,
    )
    assert calls == 1
    assert len(result["runs"]) == 8
    assert all(r["status"] == "invalid" for r in result["runs"])
    report = build_report(result["runs"], data["labels"][:2], result["replays"])
    assert report["arms"]["A"]["invalid"] == 1
    assert report["arms"]["A"]["brier"] == pytest.approx(2 / 3)


async def test_intent_failure_never_invokes_model(tmp_path):
    class Broken(Store):
        async def begin(self, *args):
            raise OSError("database unavailable")

    async def invoke(**kwargs):
        pytest.fail("provider must not be called")

    data = materials()
    result = await campaign(
        {"protocol": data["protocol"], "cases": data["development"][:1]},
        tmp_path / "broken",
        CONFIG,
        Broken(),
        "test:owner",
        invoke,
        intervention_cases=0,
    )
    assert all(r["status"] == "invalid" for r in result["runs"])


async def test_retry_records_distinct_calls_same_logical_id(tmp_path):
    data = materials()
    artifacts = PilotArtifacts(
        tmp_path,
        experiment_id="fixture",
        case=data["development"][0],
        arm_id="B",
        configuration=CONFIG,
    )
    store = Store()
    calls = 0

    async def invoke(**kwargs):
        nonlocal calls
        calls += 1
        return response({"invalid": True} if calls == 1 else decision())

    runner = AttemptRunner(
        artifacts,
        recorder_for(artifacts, store, "test:owner", CONFIG["pricing"]),
        invoke,
        CampaignBudget(Decimal(5), Decimal("0.3"), Decimal("1.2")),
        24000,
    )
    await runner.call("final", {"evidence": [{"id": "returns", "content": {}}]}, 24000, final=True)
    assert len(store.starts) == 2
    assert store.starts[0][1] != store.starts[1][1]
    assert store.starts[0][2] == store.starts[1][2]
    assert [row[3] for row in store.starts] == [0, 1]
    assert runner.spent == 400


def test_campaign_cap_and_report_pairing():
    budget = CampaignBudget(Decimal("0.0001"), Decimal("0.3"), Decimal("1.2"))
    with pytest.raises(BudgetStop):
        budget.reserve(1000, 1000)
    with pytest.raises(ValueError, match="exactly one"):
        build_report([], materials()["labels"], [])
