# Project template

Copy this folder — or run `arena init projects/my_project` — once per project
you want to choose a model for.

```
my_project/
  config.yaml      models, weights, constraints, budgets   ← the whole contract
  tests.yaml       your test cases
  scorers/         optional: grading logic only you can write
  hooks.py         optional: touch outputs before they are graded
  results/         written by the arena (reports + arena.sqlite)
```

Then:

```bash
arena validate --project projects/my_project     # config + tests + credentials
arena evaluate --project projects/my_project --dry-run   # plan and cost estimate
arena evaluate --project projects/my_project
```

The four things worth getting right, in order:

1. **Test cases that look like your real traffic.** Twenty representative cases
   beat two hundred synthetic ones. Tag them (`easy`, `edge`, `billing`) so the
   report tells you *where* a model differs, not just *that* it does.
2. **Weights that match the decision.** `accuracy: 0.6, cost: 0.2, latency: 0.2`
   is a real statement about your product. Change it and the winner changes.
3. **Constraints for anything non-negotiable.** A model that cannot meet a
   deployment or privacy requirement should be disqualified, not merely ranked
   lower.
4. **Budgets and targets.** Without them, `cost` and `latency` are only scored
   relative to the other models in the run.
