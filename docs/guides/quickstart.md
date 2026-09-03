# Quickstart

A real leaderboard in about a minute, with no API key and no network.

## Install

```bash
git clone https://github.com/adityamhaske/agent-arena
cd agent-arena
pip install -e .
```

PyPI publishing is configured but no release has been tagged yet, so install from
source for now.

## Run an example

```bash
arena evaluate --project projects/support_triage
```

```text
Agent Arena — support_triage
  4 models × 12 tests × 3 trial(s) = 144 calls in 0.0s
  Spend: $0.0199

  #  model         id             composite  accuracy  cost   latency  status
  -  ------------  -------------  ---------  --------  -----  -------  ------------
  1  sim_small     mock:small     0.853      83.3%     $0.06  190ms    ranked
  2  sim_frontier  mock:frontier  0.750      97.6%     $0.30  1,500ms  ranked
  3  sim_balanced  mock:balanced  0.744      85.7%     $0.18  620ms    ranked
  -  sim_tiny      mock:tiny      —          50.0%     $0.02  90ms     DISQUALIFIED

  Winner: sim_small  (accuracy 83.3%, cost $0.06, latency 190ms)
  ✗ sim_tiny: accuracy 50.0% below the required 70.0%
```

Those are `mock:` models — deterministic, offline, with fixed accuracy, latency
and price. No credential, no network, no spend.

## Read the result

Two things in that table are the whole point of the tool.

**The winner is not the most accurate model.** `sim_frontier` gets 97.6% right;
`sim_small` gets 83.3%. Small wins anyway, because this project weights accuracy
at 0.55, cost at 0.25 and latency at 0.20, and small is five times cheaper and
eight times faster. At this volume, with these priorities, the extra accuracy is
not worth what it costs.

Change the priorities and the winner changes. That is not a flaw in the
leaderboard — it is the leaderboard telling you that "which model is best" is not
a well-formed question until you say what you are optimising for.

**The worst model is not ranked fourth — it is `DISQUALIFIED`.** `sim_tiny` is
the cheapest and fastest thing here, and at 50% accuracy it is unusable. The
config sets `min_accuracy: 0.70`, so it gets no rank at all and the reason is
printed. A leaderboard that ranked it fourth would imply the ordering is
meaningful all the way down.

## Try changing what matters

Open `projects/support_triage/config.yaml` and change the weights:

```yaml
metrics:
  weights: {accuracy: 0.9, cost: 0.05, latency: 0.05}
```

Run it again. `sim_frontier` now wins — the ranking followed your priorities.

## See it in a browser

```bash
arena ui
```

Opens `http://localhost:8420`. It asks what job the AI is doing in plain
language, writes the same `config.yaml`, and reports the outcome as sentences
rather than scores. The what-if sliders re-rank from answers already collected —
no new calls, no new spend.

## What next

- [your-first-project.md](your-first-project.md) — your own task
- [local-models.md](local-models.md) — Ollama, LM Studio, vLLM
- [../reference/config-schema.md](../reference/config-schema.md) — every field
