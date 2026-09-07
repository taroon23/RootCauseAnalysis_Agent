# Step 1 — Ticket Generator + Verification: Summary

Status: **Verification passed.** Safe to proceed to Step 2 (decomposition engine).

## What was built

```
config/queues_config.yaml   Layer-1 "physics": queues, valid persona/vertical pairs,
                             volume shares, baseline AHT dist, CSAT dist, modality mix,
                             staffing utilization targets. Edit this to change the world.

generator/
  config_loader.py          Loads + validates the YAML (shares sum to 1, CSAT dists sum
                             to 1, persona/vertical references are valid, etc).
  distributions.py          Sampling primitives (lognormal handle time, categorical
                             CSAT, modality, persona-pair, date-of-month, CSAT response
                             mask, negative CSAT distribution shift).
  staffing.py                Agent pool / shift simulation -> agent_id + agent-hours.
  bridge.py                   Exact mix-shift/genuine-change weighted-average bridge
                             decomposition + volume bridge. Shared by the generator
                             (to calibrate injected deltas) and verify_data.py (to
                             independently recompute from raw data) — this module is
                             also the intended seed for the Step-2 decomposition engine.
  scenarios.py                Declarative definition of the 4 months' injected deltas.
  generate.py                  Main entry point: builds ticket-level DataFrames +
                             ground_truth.json per month.
  kpi.py                       KPI computation directly from ticket-level data, with
                             no knowledge of what was injected (used by verify_data.py).

data/*.csv                  Ticket-level data, one row per ticket, per month.
ground_truth/*.json          What was injected + the ANALYTICAL (config-derived, not
                             data-derived) expected decomposition for all 5 KPIs.
verify_data.py                Step 1b: independent verification script (see below).
docs/plots/*.png             KPI charts produced by verify_data.py.
```

Run order:
```
python -m generator.generate   # writes data/*.csv + ground_truth/*.json
python verify_data.py          # independent verification; exits non-zero on failure
```

Both scripts are fully deterministic (seeded per month from `global_settings.random_seed`
in the YAML config), so re-running produces byte-identical output.

## The 4 months

| Month | Type | What's injected | vs. baseline |
|---|---|---|---|
| `month_1_baseline` | control | Nothing. | — |
| `month_2_scenario_mixshift` | pure mix shift | Volume share moves from high-volume/low-AHT queues (Account & Login, Trip Issues, Order Issues) into low-volume/high-AHT queues (Safety & Incidents, Fraud & Risk, Vehicle/Equipment). No queue's own distribution changes. +6% overall volume growth (uniform) so Total Solves has a real bridge. | Blended AHT **+56s (+16.2%)**, TPH **-6.8%**, with **0% genuine contribution** anywhere — a pure mix-shift stress test. |
| `month_3_scenario_genuine` | pure genuine change | Shares held exactly at baseline (0% mix, by construction). Technical/App Support's mean handle time +35%, its CSAT distribution shifts negative, resolved rate -4pp (simulating a confusing app update). +3% uniform volume growth. | Blended AHT **+10.6s (+3.0%)**, **100% genuine** by construction. |
| `month_4_scenario_mixed` | mixed | The Month-2-style mix shift at half magnitude, **simultaneously** with a genuine handle-time/CSAT change in Payments & Billing (a new fraud-check step). Payments & Billing's handle-time multiplier is **analytically solved** (via `generator/bridge.py`) so the AHT bridge comes out to **exactly 60% mix / 40% genuine**. +4% uniform volume growth. | Blended AHT **+45.7s (+13.1%)**; realized split from raw data: **61.9% mix / 38.1% genuine** (within 2pp of the exact 60/40 target — the residual is ordinary sampling noise from ~31k ticket draws, not a bug). |

## Key design decisions (agreed before building)

1. **TPH / agent-hours**: simulated via an explicit discrete agent pool with 8-hour
   shifts per (queue, day) — see `generator/staffing.py`. Daily headcount is sized to
   the realized handle-time load at each queue's `utilization_target`. This means TPH's
   mix-shift signal comes from agent-hours reallocating across queues in *different*
   proportions than raw ticket counts (because AHT differs by queue), and TPH's
   genuine-change signal flows mechanically from handle-time changes (staffing is
   reactive, not psychic — a realistic simplification).
2. **Total Solves**: defined as **resolved** ticket count (not raw ticket volume), so it
   also picks up the resolved-rate dip injected alongside genuine-change scenarios. Every
   scenario month carries an explicit, documented overall growth/decline rate (layered
   uniformly across queues) *in addition to* any mix-shift, so Total Solves always has a
   real, non-trivial multi-queue volume bridge to decompose — otherwise a pure mix-shift
   month would show exactly 0% total-volume change by definition.
3. **Genuine change scope**: shifts both the handle-time distribution AND the CSAT
   distribution together for the targeted queue (richer signal across all 4 rate-based KPIs).
4. **CSAT response modeling**: ~29-30% realized survey response rate; unresolved tickets
   respond less often, and when they do respond, scores are softly shifted toward lower stars.
5. **Queue/persona/vertical mapping**: used my own best-judgment interpretation of the
   spec's table (documented in `config/queues_config.yaml`); exact realism wasn't required
   since it's a synthetic dataset built to support agent development.
6. **A single, exact bridge convention** ("mix-first, then rate": `mix_component = Σ Δweight·old_value`,
   `genuine_component = Σ new_weight·Δvalue`, and these sum to the total delta with **zero
   residual**) is used everywhere — generation-time calibration, ground truth, and the
   verification script's independent recomputation. This convention is not symmetric
   (a "genuine-first" convention exists too); what matters is using the same one throughout,
   since Step 2's decomposition engine must replicate it exactly to be graded correctly.
7. **Only AHT is exactly calibrated** to the Month 4 60/40 target split. TPH, CSAT 1★/5★,
   and Total Solves use different weighting schemes (agent-hours vs. ticket-count shares)
   or are a different kind of decomposition entirely (volume bridge), so forcing an
   identical ratio across all of them from one injected change isn't mathematically
   possible. Their *actual* resulting splits are logged in `ground_truth.json` for
   grading flexibility rather than being forced to match AHT's target.
8. **Note on queue count**: the spec's queue table lists 11 queues (Account & Login
   through Safety & Incidents) while the prose says "10 queues" — all 11 from the table
   are implemented, since that's the fully-specified list.

## What `verify_data.py` confirmed

- **Overall KPI table + month-over-month deltas** (printed to console) match the
  direction and rough magnitude expected from each scenario's injected effects.
- **`docs/plots/volume_share_by_queue.png`**: Month 1 and Month 3 lines are
  visually identical (flat shares, as designed for the pure-genuine scenario);
  Months 2 and 4 visibly bend toward Safety/Fraud/Vehicle and away from
  Account&Login/Trip/Order — the intended mix-shift stress test is visible by eye.
- **`docs/plots/kpis_by_queue.png`**: Payments & Billing's AHT/CSAT bars spike only
  in Month 4 (red); Technical/App Support's spike only in Month 3 (green) — confirming
  each injected genuine change lands only in its intended queue/month, nowhere else.
- **Back-of-envelope bridge check** (independent of `generate.py`'s own bookkeeping):
  recomputes the AHT weighted-average bridge and the Total Solves volume bridge
  *directly from the raw generated CSVs* and compares against the analytical values in
  `ground_truth.json`. All 3 scenario months passed within a 6-percentage-point
  tolerance (actual drift was ≤2pp in every case — pure sampling noise from ~30k tickets).
- **Data-quality flags**: zero invalid (queue, vertical, persona) combinations, zero
  non-positive handle times, zero out-of-range CSAT scores, and all KPI values within
  sane bounds, across all 4 months.

## Known simplifications to revisit later

- CSAT ground-truth values in `ground_truth.json` use the raw per-queue distribution
  directly rather than modeling the small interaction between response-rate bias and
  the unresolved-ticket score penalty — realized CSAT% is within ~1pp of this in
  practice (visible in the by-queue table), which is immaterial for Step 1's purposes
  but worth knowing about if Step 2's grading tolerances get tight.
- Agents are not persistent across days (a fresh discrete pool is "scheduled" daily).
  Fine for aggregate agent-hours math; would need revisiting if agent-level analysis
  is ever added as a dimension.
- Volume-share deltas, growth rates, and genuine-change magnitudes were chosen to make
  effects clearly visible for this stress test, not fit to any real-world benchmark.
