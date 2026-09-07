# Progress Update — Autonomous Root-Cause-Analysis Agent

## Project Recap

This project is building an AI agent that automatically investigates unexpected
movements in operations metrics — for example, how long it takes to resolve a customer
support request, or customer satisfaction scores. When a metric moves, the agent figures
out *why* it moved (a genuine change in performance, versus simply a shift in the mix of
work coming in), *where* it happened, and *how much* each factor contributed. This
mirrors real root-cause-analysis work I did professionally, where leadership needed fast,
correct answers to "why did this number move this month?"

## Simulated Data

Because the operations data this project needs (support tickets, handling times,
satisfaction scores) isn't publicly available, we built a realistic simulated dataset to
develop and test the agent against. It covers about 10 categories of support work across
different customer types, roughly 30,000 records per month over 4 months. Some months
include known, deliberately "planted" changes with documented expected answers, so we can
verify the agent's conclusions are actually correct — not just plausible-sounding.

## What's Been Completed

- **Step 1 — Simulated dataset, built and verified.** We built the dataset above,
  including scenarios with known causes, and independently confirmed the data behaves
  exactly as intended before building anything on top of it.
- **Step 2 — Core analytical engine, built and validated.** We built the engine that
  separates "the metric changed because the mix of incoming work changed" from "the
  metric changed because performance actually got better or worse." We mathematically
  confirmed this method fully accounts for the total change with no unexplained gap, and
  validated its answers against the known scenarios from Step 1 across every metric we
  track.

## What's Next

Step 3: teaching the system to automatically decide *when* a metric's movement is
significant enough to warrant investigation, so it flags real signals and ignores normal
month-to-month noise.

## A Note on Rigor

At each step, we validated results against known answers before moving forward, rather
than assuming things worked. Where a check didn't match perfectly, we investigated the
underlying cause instead of adjusting numbers until it passed — including catching and
fixing a couple of subtle issues in our own validation data along the way. That habit is
the point of this project: proving the agent is actually correct, not just
convincing-sounding.
