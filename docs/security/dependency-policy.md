# Dependency policy

The engine is stdlib-only. PyYAML is the single runtime dependency and even that
is optional — JSON config works without it. This is invariant 1 in
[../../AGENTS.md](../../AGENTS.md), and it is a security posture as much as an
engineering one.

## The security argument

**Supply-chain surface is near zero.** The most common way a Python tool
compromises its user is a dependency — directly, or transitively through a
dependency's dependency. A package with no dependency tree cannot be attacked
that way. Given that this tool holds API keys and spends money, that matters more
than it would for a library that does neither.

**No transitive CVE treadmill.** There is no quarterly scramble to bump a
sub-dependency of a sub-dependency. The audit surface is the code in this
repository.

**It works on a locked-down machine.** Plenty of the people who most need this
tool — in regulated environments, on managed laptops, behind an artifact proxy —
cannot casually install fifty packages. `pip install agent-arena` is instant and
uncontroversial.

**Reviewability.** A security reviewer can read the whole thing. That is not true
of a tool that pulls in a web framework, an HTTP client, a validation library and
their trees.

## How provider SDKs stay optional

Every SDK is imported inside the method that needs it:

```python
def _require(module: str, extra: str):
    try:
        return __import__(module)
    except ImportError as exc:
        raise ConnectorError(
            f"the {extra!r} provider needs the {module!r} package: "
            f"pip install 'agent-arena[{extra}]'"
        ) from exc
```

You install only what you actually call:

```bash
pip install agent-arena                 # engine + CLI, pyyaml only
pip install 'agent-arena[anthropic]'    # + the Anthropic SDK
pip install 'agent-arena[all]'          # every provider
```

The CI test job installs **no** provider SDK on purpose. If the suite ever needs
`anthropic` present to pass, the invariant has been broken and the build says so.

## Things written by hand rather than depended on

| Instead of | This repo has | Why |
|---|---|---|
| `python-dotenv` | `core/env.py` | ~190 lines against a package plus its tree |
| `keyring` | `service/secrets.py` via the platform tool | Native binaries are already installed and already trusted |
| `requests` / `httpx` | `urllib` in `connectors/local.py` | A local endpoint is a plain HTTP POST |
| Flask / FastAPI | `http.server` in `web/server.py` | The routing table is 12 lines |
| `pydantic` | Hand-written validators in `core/config.py` | Error messages can point at the offending config line |
| `tenacity` | `core/retry.py` | The policy is provider-specific anyway |

Each is a real trade. The hand-written versions are smaller in scope and have to
be tested properly — which is why `core/env.py` and `service/secrets.py` have
dedicated test modules covering their edge cases.

## The bar for a new dependency

A proposal has to answer all of these:

1. **Can the stdlib do it?** Usually yes, at a size worth writing.
2. **Is it in the engine or somewhere optional?** An optional extra behind a lazy
   import is a much lower bar than a runtime dependency.
3. **What is its own dependency tree?** A package with fifteen transitive
   dependencies is fifteen decisions, not one.
4. **What breaks without it?** If the answer is "the code is longer", that is not
   sufficient.
5. **Who maintains it, and what happens if they stop?**

The v2 plan's `[ui]` extra — FastAPI plus a pre-built front-end bundle — is
scoped exactly this way: an **optional** extra, so the default install stays
stdlib-only and CI keeps proving it.

## Verifying the invariant yourself

```bash
pip install -e .
python3 -c "import agent_arena; print('clean')"
pip list --not-required --format=freeze     # should show pyyaml and little else
python3 -m pytest -q                        # full suite, no provider SDK
```
