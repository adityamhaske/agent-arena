# Comparing pipelines

Most shipped systems are not one prompt to one model. They retrieve, plan, call
tools, critique, synthesise. A **target** puts one of those on the leaderboard
beside a plain model.

## The shape

```yaml
targets:
  - key: rag_v1
    run: pipelines/rag.py:answer          # any callable

  - key: rag_v2_with_critic
    run: pipelines/rag.py:answer
    params: {critic: true}                # same callable, different config

models:
  - key: single_call_baseline             # the control, in the same run
    model: claude-sonnet-5
```

`targets:` and `models:` are one list under two names. A pipeline is graded,
ranked and disqualified by exactly the machinery a model is.

## The callable

Minimum:

```python
# pipelines/rag.py
def answer(prompt, **ctx):
    return "..."
```

Or report your own spend and metrics:

```python
def answer(prompt, critic=False, **ctx):
    docs = retrieve(prompt)
    draft = llm(f"{docs}\n\n{prompt}")
    if critic:
        draft = llm(f"Check this: {draft}")
    return {
        "text": draft,
        "cost_usd": 0.0031,                    # your real end-to-end spend
        "metrics": {"docs_retrieved": len(docs), "critic_passes": int(critic)},
    }
```

When you return `cost_usd`, the arena **trusts it over the price catalog**. A
pipeline is the only thing that knows what its internal calls cost — the catalog
sees one opaque call.

`metrics` entries become weightable dimensions by name, exactly like a builtin.

## The worked example

`projects/pipeline_demo/` compares three multi-agent architectures on one task,
offline and deterministic:

```bash
arena evaluate --project projects/pipeline_demo
```

```text
  #  model              composite  accuracy  cost   latency  status
  -  -----------------  ---------  --------  -----  -------  ------------
  1  single_agent       0.907      100.0%    $0.90  220ms    ranked
  -  peer_to_peer       —          27.3%     $1.80  440ms    DISQUALIFIED
  -  supervisor_worker  —          63.6%     $2.70  660ms    DISQUALIFIED

  Winner: single_agent  (accuracy 100.0%, cost $0.90, latency 220ms)
  ✗ peer_to_peer: accuracy 27.3% below the required 80.0%
  ✗ supervisor_worker: accuracy 63.6% below the required 80.0%
  ! Only one model cleared the hard constraints, so the ranking is not a comparison.
```

### What that result means

One fact — is the account on credit hold? — is seen by the first stage and needed
by the last.

- `peer_to_peer` uses a **rigid fixed-format handoff** with no field for it, so it
  loses the fact every time. 27.3%.
- `supervisor_worker` uses a **free-text summary**, which keeps the fact when it
  is prominent and drops it when it is buried. 63.6% — the intermittent failure
  that reads like a prompt problem for weeks.
- `single_agent` never hands off, so it cannot lose anything. 100%.

The extra agents show up as real money in the cost column: three times the calls
for worse accuracy.

Note the last line. When only one entry clears the constraints, the arena says
the ranking is not a comparison rather than presenting a one-model leaderboard as
if it were one.

## Why this matters

This is where the two halves of the repository meet. The
[multi-agent handoff study](../../studies/multi_agent_handoff/README.md) proved
that coordination failure exists and is separable from capability failure. This
makes it **rankable, costable and gated on**.

They answer different questions about the same axis, and you need both. The study
asks *why* a pipeline failed and answers from a replayable trace with a failure
taxonomy. The arena asks *which design should we ship, and what does it cost*,
and answers from the outside without knowing why.

## Practical notes

- **Always include a single-call baseline.** A pipeline that cannot beat one
  well-prompted model call is not earning its complexity, and without the control
  in the same run you will not know.
- **Vary one thing.** Two targets pointing at the same callable with different
  `params` isolates the change. Two different callables confound it.
- **Report your real cost.** Otherwise the catalog prices one call and a
  five-call pipeline looks as cheap as a single-call baseline.
- **Latency is end to end.** A pipeline's latency is the sum of its stages, and
  that is usually where the complexity shows up first.
