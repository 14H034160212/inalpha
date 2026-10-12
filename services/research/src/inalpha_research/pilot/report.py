"""Deterministic paired development reporting and intervention construction."""

from __future__ import annotations

import copy
import random
import statistics
from typing import Any

from .artifacts import safe_json


def intervention_plans(run: dict[str, Any], case: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep earlier turns, modify the selected last-round contribution, replay downstream."""
    if run["status"] != "completed":
        return [{"name": "interventions", "skip": "INVALID_BASE_RUN"}]
    history = run["history"]
    candidates = [(i, row) for i, row in enumerate(history) if "output" in row]
    if not candidates:
        return [{"name": "interventions", "skip": "NO_COMPLETED_TURN"}]
    last = max(row["round"] for _, row in candidates)
    probs = ("p_up", "p_flat", "p_down")
    selected, row = min(
        ((i, row) for i, row in candidates if row["round"] == last),
        key=lambda item: (
            sum(abs(item[1]["output"][p] - run["decision"][p]) for p in probs),
            item[0],
        ),
    )
    prefix = copy.deepcopy(history[: selected + 1])
    deleted = copy.deepcopy(prefix)
    deleted[-1] = {"role": row["role"], "round": row["round"], "removed": True}
    flipped = copy.deepcopy(prefix)
    decision = flipped[-1]["output"]
    decision["p_up"], decision["p_down"] = decision["p_down"], decision["p_up"]
    decision["action"] = -decision["action"] if decision["action"] else 1
    decision["rationale"] = "Intervention: the analyst's stated conclusion is reversed."
    placebo = copy.deepcopy(prefix)
    length = len(safe_json(row["output"]))
    placebo[-1] = {
        "role": row["role"],
        "round": row["round"],
        "unrelated_replacement": ("A fictional room has plain walls. " * (length // 33 + 1))[
            :length
        ],
    }
    plans = [
        {"name": "delete_contribution", "prefix": deleted},
        {
            "name": "replace_contribution",
            "prefix": placebo,
            "matching": "approximate character length, not exact provider tokens",
        },
        {"name": "flip_conclusion", "prefix": flipped},
        {"name": "downstream_noise", "prefix": prefix, "stochastic_replicate": True},
    ]
    cited = run["decision"]["cited_evidence_ids"]
    if not cited:
        plans.append({"name": "remove_evidence", "skip": "NO_CITED_EVIDENCE"})
    else:
        removed = cited[0]
        items = {e["id"]: e for e in case["evidence"]}
        plans.append({"name": "remove_evidence", "remove_evidence": removed})
        uncited = [key for key in items if key not in cited]
        if uncited:
            target = min(
                uncited,
                key=lambda key: (
                    abs(
                        len(safe_json(items[key]["content"]))
                        - len(safe_json(items[removed]["content"]))
                    ),
                    key,
                ),
            )
            plans.append({"name": "remove_placebo_evidence", "remove_evidence": target})
        else:
            plans.append({"name": "remove_placebo_evidence", "skip": "NO_UNCITED_EVIDENCE"})
        plans.append({"name": "round_zero_noise", "stochastic_replicate": True})
    return plans


def metrics(run: dict[str, Any], label: dict[str, Any]) -> dict[str, float]:
    """Invalid runs remain in intention-to-treat metrics using protocol's uniform fallback."""
    invalid = run["status"] != "completed"
    value = (
        {"p_up": 1 / 3, "p_flat": 1 / 3, "p_down": 1 / 3, "action": 0}
        if invalid
        else run["decision"]
    )
    action = int(value["action"])
    category = {1: "UP", 0: "FLAT", -1: "DOWN"}[action]
    pnl = action * label["excess_return"]
    return {
        "brier": sum(
            (value[key] - (label["value"] == cls)) ** 2
            for key, cls in zip(("p_up", "p_flat", "p_down"), ("UP", "FLAT", "DOWN"), strict=True)
        ),
        "hit": float(category == label["value"]),
        "coverage": float(action != 0),
        "invalid": float(invalid),
        "pnl_20bp": pnl - 0.002 * abs(action),
        "pnl_0bp": pnl,
        "pnl_50bp": pnl - 0.005 * abs(action),
    }


def paired_interval(values: list[float], block: int = 5) -> dict[str, Any]:
    """Seeded moving-block bootstrap; tiny development intervals are descriptive only."""
    if len(values) < block:
        return {"difference": statistics.mean(values), "interval": None, "reason": "TOO_FEW_CASES"}
    rng = random.Random(206)
    means = []
    for _ in range(1000):
        sample: list[float] = []
        while len(sample) < len(values):
            start = rng.randrange(len(values) - block + 1)
            sample.extend(values[start : start + block])
        means.append(statistics.mean(sample[: len(values)]))
    means.sort()
    return {
        "difference": statistics.mean(values),
        "interval": [means[24], means[974]],
        "block_length": block,
    }


def build_report(
    runs: list[dict[str, Any]], labels: list[dict[str, Any]], replays: list[dict[str, Any]]
) -> dict[str, Any]:
    """Require paired four-arm coverage; never silently drop missing or invalid cases."""
    by_case = {label["case_id"]: label for label in labels}
    lookup = {(r["case_id"], r["arm"]): r for r in runs}
    if len(lookup) != len(runs) or set(lookup) != {
        (case, arm) for case in by_case for arm in "ABCD"
    }:
        raise ValueError("exactly one run per case and arm required")
    scored = {
        (case, arm): metrics(lookup[case, arm], label)
        for case, label in by_case.items()
        for arm in "ABCD"
    }
    arms = {
        arm: {
            key: statistics.mean(scored[case, arm][key] for case in by_case)
            for key in next(iter(scored.values()))
        }
        for arm in "ABCD"
    }
    complete = [
        case
        for case in by_case
        if all(lookup[case, arm]["status"] == "completed" for arm in "ABCD")
    ]
    paired = {
        f"{a}-{b}": paired_interval(
            [scored[case, a]["brier"] - scored[case, b]["brier"] for case in by_case]
        )
        for a, b in (("B", "A"), ("C", "A"), ("D", "A"), ("D", "B"), ("D", "C"))
    }
    intervention_rows = []
    for replay in replays:
        if "skip" in replay:
            intervention_rows.append(replay)
            continue
        base = lookup[replay["case_id"], "D"]
        valid = replay["status"] == base["status"] == "completed"
        intervention_rows.append(
            {
                "case_id": replay["case_id"],
                "name": replay["replay"]["name"],
                "status": replay["status"],
                "flip": float(replay["decision"]["action"] != base["decision"]["action"])
                if valid
                else None,
                "brier_change": metrics(replay, by_case[replay["case_id"]])["brier"]
                - metrics(base, by_case[replay["case_id"]])["brier"],
                "original_class_probability_change": (
                    replay["decision"][
                        max(("p_up", "p_flat", "p_down"), key=lambda k: base["decision"][k])
                    ]
                    - max(base["decision"][k] for k in ("p_up", "p_flat", "p_down"))
                )
                if valid
                else None,
                "reentry": replay.get("reentry"),
            }
        )
    noise = {(row["case_id"], row["name"]): row for row in intervention_rows if "flip" in row}
    for row in intervention_rows:
        if "flip" not in row:
            continue
        baseline_name = (
            "round_zero_noise"
            if row["name"] in ("remove_evidence", "remove_placebo_evidence")
            else "downstream_noise"
        )
        baseline = noise.get((row["case_id"], baseline_name), {})
        row["noise_adjusted_flip"] = (
            row["flip"] - baseline["flip"]
            if row["flip"] is not None and baseline.get("flip") is not None
            else None
        )
    budgets = {
        arm: {
            "median_actual_known_tokens": statistics.median(
                [
                    sum(
                        c["usage"]["input_tokens"] + c["usage"]["output_tokens"]
                        for c in r["calls"]
                        if c["usage"].get("usage_status") == "known"
                    )
                    for r in runs
                    if r["arm"] == arm
                ]
            ),
            "unknown_attempts": sum(
                c["usage"].get("usage_status") != "known"
                for r in runs
                if r["arm"] == arm
                for c in r["calls"]
            ),
        }
        for arm in "ABCD"
    }
    medians = [budgets[arm]["median_actual_known_tokens"] for arm in "BCD"]
    reference = statistics.mean(medians)
    budget_match = (
        reference > 0
        and all(abs(m / reference - 1) <= 0.1 for m in medians)
        and not any(budgets[arm]["unknown_attempts"] for arm in "BCD")
    )
    return {
        "compute_match_within_10_percent": budget_match,
        "scope": "development machinery validation; no superiority or causal attribution",
        "arms": arms,
        "paired_brier": paired,
        "complete_case_count": len(complete),
        "complete_case_arms": {
            arm: {
                key: statistics.mean(scored[c, arm][key] for c in complete)
                for key in next(iter(scored.values()))
            }
            for arm in "ABCD"
        }
        if complete
        else {},
        "budgets": budgets,
        "interventions": intervention_rows,
        "limitations": [
            "budget matching requires development calibration before formal freeze",
            "model revision and training cutoff unknown",
            "historical vendor revisions cannot be excluded",
            "human process review pending",
            "intervention replacement matches characters, not exact provider tokens",
            "noise uses a fresh stochastic call; provider seed support is not assumed",
        ],
    }
