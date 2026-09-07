# Autonomous Root-Cause-Analysis (RCA) Agent

This project builds an AI agent that automatically investigates unexpected movements in
operations metrics (like support-ticket handling time or customer satisfaction), figures
out whether the cause is a genuine change in performance or just a shift in the mix of
incoming work, identifies where it happened, and quantifies how much each factor
contributed. It's modeled on real root-cause-analysis work done professionally at a
large tech company, and is being developed as a graduate research project. Because real
operations data isn't publicly available, the project uses a realistic simulated dataset
with documented "known answers" so the agent's conclusions can be independently verified
at every step, not just judged on how plausible they sound.

**Current status:** Steps 1-2 complete (simulated data + core decomposition engine, both
independently validated). See [`summaries/progress_update_1.md`](summaries/progress_update_1.md)
for a plain-language status update, or the technical writeups below for details.

## Repository structure

```
config/         Editable "world" definition: queues, customer segments, baseline
                 statistical distributions, staffing parameters (YAML).
generator/       Ticket-level synthetic data generator + injected test scenarios.
data/            Generated ticket-level CSVs, one file per simulated month.
ground_truth/    Machine-readable record of exactly what was injected into each
                 simulated month, used to grade the agent's work.
engine/          The standalone decomposition engine (Step 2) — recovers mix-shift vs.
                 genuine-change splits from raw data alone, with no knowledge of what
                 was injected.
docs/            Technical writeups per step (method, design decisions, validation
                 results) plus supporting charts.
summaries/       Plain-language, non-technical progress updates for stakeholders.
verify_data.py         Step 1 independent verification script.
validate_engine.py     Step 2 validation script (the decomposition engine's hard gate).
```

## Quickstart

```
pip install -r requirements.txt
python -m generator.generate    # writes data/*.csv + ground_truth/*.json
python verify_data.py           # Step 1 independent verification (exit 0 = safe to proceed)

python -m engine.run_decomposition --kpi ALL --comparison-type prior_month \
    --baseline month_1_baseline --current month_2_scenario_mixshift
python validate_engine.py       # Step 2 hard gate (exit 0 = safe to proceed)
```

## Roadmap

1. ~~Ticket generator + verification~~ ✅ done (Step 1)
2. ~~Decomposition engine~~ ✅ done (Step 2) — validated against `ground_truth/`
3. Anomaly detection layer (in progress/next)
4. LLM agent orchestration (calls the decomposition engine as a tool)
5. Executive summary generation (business language, no analyst jargon)
6. Expansion to a second dimension (persona/modality/region) + trend-based detection
7. Automated grading harness (agent output vs. ground truth)
