# Four-arm development pilot (#206 / #208)

The local command chain prepares aligned data, freezes relative evidence, runs all four
arms with the unified ledger, replays interventions, and produces paired development
metrics. It does not freeze the formal protocol, claim compute matching before calibration,
or replace Qiming's protocol review. The starting settings implement the v0.1 discussion
on #206; the configuration must be reviewed and frozen before formal evaluation.

## Prepare inputs

From `services/research`:

```bash
uv sync --group pilot
uv run --group pilot python -m inalpha_research.pilot.materials /private/path/materials
uv run python -m inalpha_research.pilot validate /private/path/materials/materials.json
```

Defaults fetch TSLA and SPY from Yahoo Finance with `auto_adjust=False`, daily OHLCV,
from 2024-05-07 through 2026-07-07 inclusive. Both series must exactly match XNYS
sessions. Source retrieval time, library version, raw rows and content hashes are retained.
`--market /path/market.json` reuses a snapshot without another network request.

Ten consecutive development cases start 2026-05-01. Each uses a 252-session lookback.
Asset and benchmark returns, volatility, volume ratio and range position are model-visible;
tickers, dates, absolute prices, source hashes and outcomes are not. Daily-close availability
is an explicit historical assumption, not observed archival availability; vendor revisions
cannot be excluded. Returns use unadjusted prices, exclude dividend cashflows and ignore
borrow costs. Split-containing periods require a revised protocol before use.

The outcome enters at the next session open and exits five sessions later. Labels use
`tau = 0.5 * sample_std(five-session excess returns)`, calibrated only on windows whose
exit strictly precedes the first development case. Costs are 20 bp round trip, with 0/50 bp
sensitivity. Outcome labels live separately from `inputs.json` and are only opened by the
report command. The deterministic pre-run process rubric is not a human annotation or
inter-rater agreement claim. The formal split is empty; do not reuse these development
windows as formal evaluation cases.

## Run after budget authorization

Use an authorized local/test Postgres database with migration 0066 applied. Set
`DATABASE_URL` and `DEEPSEEK_API_KEY` in the process environment without printing them.
The explicit `--owner` is the authorized operator identity for this standalone run, not
an unauthenticated web request parameter. Do not use this CLI to impersonate a production
user. Credentials are never written into manifests, prompts or ledger links.

```bash
uv run python -m inalpha_research.pilot.campaign run \
  /private/path/materials/inputs.json /private/path/campaign \
  --config examples/pilot/development-config.json --owner '<authorized-owner>'
uv run python -m inalpha_research.pilot.campaign report \
  /private/path/campaign /private/path/materials/outcomes.json
```

The example $5 configuration is a proposal, not authorization to spend. A campaign creates
an exclusive directory and never silently resumes or overwrites a prior paid run. API SDK
retries are disabled. Each attempted final answer may retry once, within the remaining
budget; every attempt persists an intent first and uses the shared `UsageRecorder`.
Unconfirmed ledger settlement or unknown provider usage stops further paid calls.
Unknown attempts retain the full cost/token reservation, never zero. Failures remain in
the paired dataset. Interrupted directories retain call events and must be investigated;
there is no automatic paid replay.

Input reservations conservatively use UTF-8 bytes plus framing allowance, not an exact
provider tokenizer. Actual reported usage reconciles each reservation; an overrun stops
the campaign. Therefore this is an observed guard with a conservative preflight estimate,
not a mathematical claim that provider tokenization or billing cannot exceed a bound.
Prices are frozen peak/non-cache estimates, not invoices. The example metadata records
the provider-documented version separately from unknown immutable revision/training cutoff.

## Arm and replay semantics

- A: one independent final decision, lower-budget reference.
- B: fixed independent samples and aggregation.
- C: fixed sequential reflection/revision units and final decision.
- D: fixed bull/bear/risk turns across configured rounds and final synthesis. It uses the
  production research roles in an isolated price-only adapter, without live tools,
  disagreement-trigger skips or convergence early exits. Budget exhaustion can shorten
  the run and is recorded along with completed units.

The working stage may consume at most 85% of the arm token cap. Final aggregation has
at least 15% reserved, including its prompt. Defaults are machinery-smoke settings;
calibrate B/C/D sample counts and rounds on separate development runs until provider-
reported median usage is within 10%, then freeze. `compute_match_within_10_percent` reports
observed matching; a successful command does not imply matching or scientific readiness.

Interventions modify the closest-probability analyst in the last completed round (stable
turn-order tie-break), preserve the earlier prefix and replay all later turns. Contribution
removal has an unrelated character-length replacement control. Conclusion flipping is an
explicit edited message; it does not ask the model to cooperate with an instruction to flip.
Evidence removal drops the first cited evidence block and replays from round zero, with
an uncited similar-length placebo where available. Missing controls receive explicit skip
reasons. Fresh stochastic noise reruns use the same replay boundaries; no unsupported
provider seed guarantee is made. Literal ID/numeric scans report possible evidence re-entry,
with rounded/inferred reconstruction remaining a limitation.

The report includes multiclass Brier, hit/coverage/invalid rates, net excess returns,
intention-to-treat uniform probabilities for invalid runs, complete-case results,
paired moving-block bootstrap intervals, usage, intervention flip/probability/Brier changes
and noise-adjusted flip differences. Character matching is not exact tokenizer matching;
formal intervention controls and blinded human process scoring still need protocol review.

A 10-case run validates the machinery. Retain negative/inconclusive results and limitations.
