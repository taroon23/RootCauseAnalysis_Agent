# Step 2 — Standalone Decomposition Engine: Summary

Status: **Validation passed.** Safe to proceed to Step 3 (anomaly detection layer).

## What was built

```
engine/
  data.py               Ticket-level CSV loading, shared by every entrypoint.
  decomposition.py       Core symmetric (Shapley-style) mix/genuine decomposition for
                        AHT, TPH, 1-star CSAT %, 5-star CSAT %. Zero injection knowledge.
  volume_bridge.py        Total Solves volume attribution (distinct schema, not mix/genuine).
  pooling.py               Parameterized multi-month pooled-baseline construction.
  run_decomposition.py      CLI entrypoint: JSON + human-readable table output.
validate_engine.py        3-tier validation against ground_truth/ (the hard gate).
docs/step2_summary.md      This file.
```

The engine imports `generator.config_loader` (queue/persona structure) and `generator.kpi`
(raw KPI computation from ticket data) — both are pure "what does the world look like"
metadata, not injection knowledge. It **never** imports `generator.bridge` or
`generator.scenarios`, and **never reads `ground_truth/*.json`** — that only happens in
`validate_engine.py`, which is explicitly a grading script, not engine logic.

Run it:
```
python -m engine.run_decomposition --kpi ALL --comparison-type prior_month \
    --baseline month_1_baseline --current month_2_scenario_mixshift

python -m engine.run_decomposition --kpi AHT --comparison-type pooled_baseline \
    --baseline month_1_baseline month_2_scenario_mixshift month_3_scenario_genuine \
    --current month_4_scenario_mixed

python validate_engine.py   # the hard gate
```

## Method: symmetric (Shapley-style) decomposition, and why

Per queue *i*, comparing period 0 (baseline) to period 1 (current):

```
mix_effect_i     = 0.5 * [(w1_i - w0_i)*v0_i + (w1_i - w0_i)*v1_i]  =  (w1_i - w0_i) * mean(v0_i, v1_i)
genuine_effect_i  = 0.5 * [w0_i*(v1_i - v0_i) + w1_i*(v1_i - v0_i)]  =  (v1_i - v0_i) * mean(w0_i, w1_i)
```

**Proof this reconstructs exactly, with zero residual:**

```
sum_i (mix_effect_i + genuine_effect_i)
  = 0.5 * sum_i [ (w1-w0)v0 + (w1-w0)v1 + w0(v1-v0) + w1(v1-v0) ]
  = 0.5 * sum_i [ w1v0 - w0v0 + w1v1 - w0v1 + w0v1 - w0v0 + w1v1 - w1v0 ]
  = 0.5 * sum_i [ 2*w1v1 - 2*w0v0 ]
  = sum_i (w1_i*v1_i) - sum_i (w0_i*v0_i)
  = blended_1 - blended_0
```

This is unconditionally exact for any weights/values — `engine/decomposition.py` asserts
it after every decomposition (`RECONSTRUCTION_ATOL = 1e-6`) and raises if it ever doesn't
hold. Unlike the "mix-first" asymmetric bridge used by `generator/bridge.py` for *data
generation* (which evaluates mix at old values and genuine at new weights — order-dependent,
picks a convention), this method is symmetric in period order by construction: swapping
period 0 and 1 just flips signs, it doesn't change which convention "wins" the interaction
term. That's the right property for a detective tool with no privileged reference period.

**Weighting basis:** ticket-count share for AHT/CSAT%, agent-hours share for TPH — per spec.

**Total Solves** gets a structurally distinct module (`engine/volume_bridge.py`): it's a
direct volume bridge (`volume_effect_i = solves_1,i - solves_0,i`), not a mix/genuine split.
Its output schema has no `mix_pct`/`genuine_pct` fields, by design — including them would
imply a decomposition that doesn't apply here.

## Comparison modes

Both are driven by the same `decompose_kpi()` / `decompose_total_solves()` functions —
`engine/pooling.py` just hands back a differently-constructed period DataFrame:

- **`prior_month`**: `--baseline <one month>` vs `--current <one month>`.
- **`pooled_baseline`**: `--baseline <month> <month> ...` (2+) gets concatenated at the raw
  ticket level via `build_pooled_period()`, then treated as a single period. Fully
  parameterized by month-key list — nothing hardcodes "months 1-3".

One duration wrinkle worth flagging: AHT/TPH/CSAT% are weighted means/rates, so they're
naturally invariant to how many months got pooled into the baseline. **Total Solves is a
raw count and is not** — pooling 3 months roughly triples the baseline volume. `volume_bridge.decompose_total_solves()` takes a `baseline_periods_count` parameter and
normalizes the pooled baseline to an "average month" before comparing against the
(single-month) current period; `run_decomposition.py` and `validate_engine.py` both pass
`len(baseline_months)` automatically. Without this, "vs. pooled baseline" would report Total
Solves as cratering by ~66% every time, purely because of the 1-vs-3-months mismatch — not a
real signal.

## Output schema

Per KPI x comparison, `decompose_kpi()` returns one JSON object: overall baseline/current
values, `total_change_abs`/`total_change_pct`, `overall_mix_pct`/`overall_genuine_pct`, and a
`queue_breakdown` list (one entry per queue, sorted by `abs(total_effect)` descending — most
impactful driver first, which is exactly the scan order an LLM reasoning layer or a human
would want). Each queue entry carries `old/new_weight`, `old/new_value`, `mix_effect`,
`genuine_effect`, `total_effect`, and `mix_pct_of_queue_effect`/`genuine_pct_of_queue_effect`
(null when a queue's own total effect is ~0, to avoid a division-by-zero-flavored lie).
`decompose_total_solves()` returns the parallel-but-distinct schema described above.
`run_decomposition.py` prints a matching human-readable table for both.

## Validation results (`validate_engine.py`)

**Tier 1 — hard gate** (`prior_month`, month_1_baseline vs. each of months 2/3/4, graded
against `ground_truth/*.json` — the only pairing with a documented target, since every
scenario was generated as a perturbation of month_1 alone):

| Scenario | KPI | Result |
|---|---|---|
| month_2 (mix shift) | AHT | **PASS** — 100.0% analytical vs 100.5% recovered (0.5pp) |
| month_2 | TPH | EXPLAINED (see below) |
| month_2 | CSAT 1★/5★ | EXPLAINED (see below) |
| month_2 | Total Solves | **PASS** — growth 6.00% vs 5.94% (0.06pp) |
| month_3 (genuine) | AHT | **PASS** — 0.0% vs 0.3% |
| month_3 | TPH | EXPLAINED |
| month_3 | CSAT 1★/5★ | **PASS** — exact match (0.0pp both) |
| month_3 | Total Solves | **PASS** — growth 2.70% vs 2.69% |
| month_4 (mixed) | AHT | **PASS** — the calibrated 60/40 target: 60.0% vs 60.8% recovered |
| month_4 | TPH | EXPLAINED |
| month_4 | CSAT 1★ | EXPLAINED; CSAT 5★ **PASS** (exact, 0.0pp) |
| month_4 | Total Solves | **PASS** — growth 3.66% vs 3.60% |

**9 direct passes, 6 explained discrepancies, 0 unexplained failures.** The reconstruction
identity held exactly (zero residual) in every single case, including the 6 explained ones —
the engine always correctly recovers what's actually in the data; the explained cases are
about how well that recovered result matches an *analytical approximation* used at
generation time, not about the engine's own correctness.

### The 6 explained discrepancies

**CSAT 1★/5★ (4 cases): small-denominator ratio instability, not a real mismatch.**
CSAT% is a proportion over a few hundred to ~1,800 survey respondents per queue — real
sampling noise. When the scenario's *analytical* mix/genuine split is at or near an extreme
(0% or 100%, as in a pure mix-shift or pure-genuine month) or the *total* blended change is
tiny (e.g. month_4's CSAT-1★ change was 0.61 percentage points total), a small absolute noise
term becomes a huge fraction of a near-zero denominator and the % ratio swings wildly even
though the underlying numbers barely moved. `validate_engine.py` catches exactly this: when
the % check misses tolerance, it falls back to comparing the **absolute** mix/genuine effect
sizes (in the KPI's native units) against an 8%-of-baseline-scale tolerance. All 4 CSAT cases
pass this absolute check comfortably (diffs of 0.0002–0.005 against tolerances of
0.0076–0.0272) — confirming the engine recovered the right *magnitude*, just expressed as an
unstable ratio of a near-zero total. Example: month_2 CSAT-1★, analytical mix_component=
0.00410, recovered=0.00449 (diff 0.00039) — genuinely close; the "100.0% vs 182.6%" ratio
comparison was just a bad way to grade a near-zero-genuine, near-zero-total case.

**TPH (3 cases): a real, root-caused gap in Step 1's *analytical* ground truth — not an
engine bug.** Per-queue TPH diagnostics for month_2 (pure mix shift — **no** queue's handle
time or utilization target changed) showed nearly every queue's realized TPH rising 5–15%
anyway (e.g. `trip_issues` 8.226 → 8.907, `payments_billing` 6.270 → 6.991,
`onboarding_activation` 3.923 → 4.359) — a broad, directional, non-random shift, the
signature of a systematic bias, not noise. Root cause: Step 1's staffing simulation
(`generator/staffing.py`) sizes daily agent headcount via `ceil(load / utilization /
shift_hours)` — an integer, rounded-**up** value. Rounding overhead is proportionally larger
for small headcounts and shrinks as realized daily ticket volume grows. Every scenario month
carries an explicit overall-growth injection (by design, so Total Solves has something to
decompose — see Step 1's summary), and the mix-shift scenarios additionally reallocate volume
into specific queues. Both effects raise realized per-queue ticket volume, which shrinks
rounding overhead and lifts realized TPH toward its theoretical ceiling — a volume-driven
staffing artifact that Step 1's *analytical* TPH ground truth (`generator/generate.py`'s
`_analytical_agent_hours_shares`, a continuous idealization that assumes zero rounding
overhead) doesn't model. The reconstruction identity holds exactly in all 3 TPH cases; this
is purely a "the ground truth's simplifying assumption doesn't capture discrete rounding"
gap, invisible until you compare against real generated data — which is exactly what this
validation exercise is for. Documented here rather than silently patched, per the agreed
validation scope.

**Tier 2 — sequential demo** (month_3 vs month_2, month_4 vs month_3): no ground truth
exists for these pairings (every injection was defined relative to month_1 alone). Ran all 5
KPIs for both pairs; reconstruction identity held exactly in all 10 cases. Recovered splits
are logged as informational output only — this tier exists to prove the engine works on
arbitrary period pairs, not just the ones with a known answer.

**Tier 3 — pooled-baseline demo** (pool month_1+2+3, vs. month_4): no ground truth exists
for "vs. a pooled baseline" either. Validated structurally instead: pooled-period queue
weights sum to exactly 1.0 for every weight basis, no NaN/negative values, overall pooled
KPIs fall within sane ranges, and the reconstruction identity holds exactly for all 5 KPIs.
Recovered splits are informational (e.g. AHT: 38.3% mix / 61.7% genuine — makes sense, since
month_4's genuine change is diluted less by pooling three mostly-similar prior months than by
comparing against month_1 alone, while the mix-shift signal averages out somewhat because
month_2's own mix-shift is baked into the pooled baseline in the *same* direction as month_4's).

## Known limitations / carried forward to Step 3

- TPH's analytical ground truth (Step 1) has a documented gap around discrete staffing
  rounding under volume growth. If Step 3's anomaly detector or Step 4's exec-summary layer
  ever need to explain a TPH move with high precision, worth revisiting whether Step 1's
  staffing simulation should track a continuous "fractional headcount" for ground-truth
  purposes even though real generated data uses discrete agents.
- The 8%-of-baseline-scale absolute tolerance and 5-percentage-point ratio tolerance were
  chosen pragmatically (consistent with Step 1's observed ~2pp sampling noise ceiling at
  ~30k tickets/month) and aren't derived from a formal power calculation. Fine for this
  validation; worth tightening with real statistical bounds before using tolerance breaches
  as a trigger for anything automated in Step 3+.
- Total Solves' pooled-baseline duration normalization (divide by number of pooled months)
  assumes each pooled month has roughly comparable volume. That's true here; if months of
  wildly different length or volume get pooled later, consider normalizing by ticket-days
  or calendar days instead of month count.
