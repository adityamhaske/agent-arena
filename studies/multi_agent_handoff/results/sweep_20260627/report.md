# Agent Arena — Sweep Report

**Generated:** 2026-06-27 07:53  
**Sweep timestamp:** `20260627_073355`  
**Total runs:** 28 active (0 skipped/missing key)  

## Study Scope

This study evaluates coordination failure modes within a single model family (Gemini 2.5 Flash) to isolate **architectural effects** from cross-model variance. Holding the model constant means differences in pass rate, failure category, and efficiency across architectures reflect the coordination mechanism itself — not differences in model capability. Extending this evaluation to additional model families (e.g. Claude) is noted as future work in ROADMAP.md.

## 1. Completion Health

> `incomplete` = quota exhaustion or crash before a finish event.
> These are excluded from adjusted pass rates but reported as real signal.

| Metric | Value |
|---|---|
| Total active runs | 28 |
| Passed | 22 |
| Failed | 6 |
| Incomplete (quota/crash) | 0 |
| Completion rate | 100% |
| Raw pass rate | 79% |
| **Adjusted pass rate** (excl. incomplete) | **79%** |

## 2. Pass Rate by Architecture × Task

> Format: `adj_pass_rate` (n trials, n incomplete excluded).  
> Raw pass rate shown in parentheses where they differ.

### task_01

| Architecture | gemini |
|---|---|
| debate_critic | 100% (n=3) |
| peer_to_peer | 100% (n=3) |
| single_agent | 100% (n=3) |
| supervisor_worker | 67% (n=3) |

### task_02

| Architecture | gemini |
|---|---|
| debate_critic | 100% (n=3) |
| peer_to_peer | 0% (n=3) |
| single_agent | 100% (n=3) |
| supervisor_worker | 71% (n=7) |

## 3. Failure Category Breakdown

> Categories: `task_failure` · `coordination_failure` · `tool_error_unrecovered` · `incomplete`

### task_01

| Architecture | Provider | pass | task_failure | coordination_failure | tool_error_unrecovered | incomplete |
|---|---|---|---|---|---|---|
| debate_critic | gemini | 3 | 0 | 0 | 0 | 0 |
| peer_to_peer | gemini | 3 | 0 | 0 | 0 | 0 |
| single_agent | gemini | 3 | 0 | 0 | 0 | 0 |
| supervisor_worker | gemini | 2 | 1 | 0 | 0 | 0 |

### task_02

| Architecture | Provider | pass | task_failure | coordination_failure | tool_error_unrecovered | incomplete |
|---|---|---|---|---|---|---|
| debate_critic | gemini | 3 | 0 | 0 | 0 | 0 |
| peer_to_peer | gemini | 0 | 0 | 3 | 0 | 0 |
| single_agent | gemini | 3 | 0 | 0 | 0 | 0 |
| supervisor_worker | gemini | 5 | 0 | 2 | 0 | 0 |

## 4. Efficiency Score (passing runs only)

> Score: 1.0 = optimal call count. Penalised -0.05 per extra LLM call above architecture minimum.

### task_01

| Architecture | gemini mean_score | gemini mean_llm_calls |
|---|---|---|
| debate_critic | 1.00 | 6.00 |
| peer_to_peer | 0.95 | 5.00 |
| single_agent | 1.00 | 4.00 |
| supervisor_worker | 0.85 | 10.00 |

### task_02

| Architecture | gemini mean_score | gemini mean_llm_calls |
|---|---|---|
| debate_critic | 1.00 | 6.00 |
| peer_to_peer | — | — |
| single_agent | 1.00 | 4.00 |
| supervisor_worker | 0.87 | 9.60 |

## 5. task_02 Coordination Signal

> Key diagnostic for information asymmetry task.  
> `decision_saw_hold` = the decision-making agent had access to `credit_hold=True`.  
> `hold_in_handoff` = credit_hold appeared in peer_to_peer handoff message.  
> `hold_in_worker` = credit_hold appeared in supervisor_worker CRM worker summary.

| Architecture | Provider | decision_saw_hold | hold_in_handoff | hold_in_worker | adj_pass_rate |
|---|---|---|---|---|---|
| debate_critic | gemini | 3/3 | 0/3 | 0/3 | 100% |
| peer_to_peer | gemini | 0/3 | 0/3 | 0/3 | 0% |
| single_agent | gemini | 3/3 | 0/3 | 0/3 | 100% |
| supervisor_worker | gemini | 5/7 | 0/7 | 5/7 | 71% |

## 6. Interpretation Notes

### task_01 (Customer Escalation — all architectures can solve this)
- Expected: all architectures pass. Variation in score reflects LLM call efficiency.
- One `supervisor_worker` trial on task_01 failed due to a worker hallucinating tool
  execution success — a general LLM reliability issue, not evidence of architecture-specific
  information loss. With only 3 trials per cell, we cannot distinguish whether this
  failure rate differs from `single_agent`'s; this would require substantially more
  trials to detect reliably (a single failure in 3 trials is consistent with failure
  rates anywhere from a few percent to ~50%).

### task_02 (Credit Hold — information asymmetry trap)
- `peer_to_peer`: rigid handoff schema (`HANDOFF: customer_id, tier, name, status`) does not
  include `credit_hold`. Failure is **deterministic by design** (schema never updated).
  This models the real-world pattern of under-specified inter-agent API contracts.
- `supervisor_worker`: CRM Worker summarizes in free text. Whether `credit_hold` appears
  in the summary is **model-dependent and probabilistic**. Variance across trials is the signal.
- `single_agent` / `debate_critic`: Should pass reliably. Failures here indicate model
  reasoning errors unrelated to coordination.

### On `incomplete` runs
- These are quota (429) or crash failures. They are **infrastructure noise**, not
  architecture signal. Adjusted pass rate (excluding them) is the primary metric.
- Raw pass rate is shown for transparency. A high incomplete count in a specific
  architecture (e.g. supervisor_worker making more LLM calls) is itself real signal
  about infrastructure cost of that architecture.

### On model scope
- All runs use `gemini-2.5-flash`. This is a deliberate design choice: holding the
  model constant means all observed variance in pass rate and failure category is
  attributable to the coordination architecture, not to model differences.
- Cross-model replication (e.g. Claude) is future work. The key claims in this report
  are architectural, not model-specific, and are expected to generalise.

---
*Generated by `report_generator.py`*