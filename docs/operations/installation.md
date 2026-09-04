# Installation

## Requirements

Python 3.10, 3.11, 3.12 or 3.13. CI tests all four.

## Install

A `2.0.0rc3` release candidate is on **TestPyPI**; nothing has been tagged on
the real index yet. Three ways to get it, in order of least commitment:

**Try the release candidate with `uvx`, no install at all:**

```bash
uvx --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    --from agent-arena==2.0.0rc3 arena --version
```

**Install the release candidate:**

```bash
pip install --index-url https://test.pypi.org/simple/ \
             --extra-index-url https://pypi.org/simple/ \
             agent-arena==2.0.0rc3
```

The `--extra-index-url` is needed because TestPyPI does not mirror PyPI — it
is where `pyyaml`, the one real dependency, actually comes from.

**Or install from source**, which always tracks `main`:

```bash
git clone https://github.com/adityamhaske/agent-arena
cd agent-arena
pip install -e .
```

Any of the three gives you the engine and the CLI. One dependency: PyYAML, and
even that is optional — JSON config works without it.

## Docker

```bash
docker build --build-arg PIP_INDEX_URL=https://test.pypi.org/simple/ \
  -t agent-arena .
docker run -p 8420:8420 -v $(pwd)/projects:/data/projects agent-arena
```

Drop `--build-arg PIP_INDEX_URL=...` once a real release is tagged; the
Dockerfile then installs the same package from PyPI directly.

`arena ui` has no authentication by design, and inside a container reaching it
at all requires binding `0.0.0.0` — which the image does. That means anyone
who can reach the published port can read and edit every mounted project and
spend API credit through it. Put it behind your own network boundary; never
publish the port straight to the open internet. See
[../security/hardening.md](../security/hardening.md).

For one-shot CLI use instead of the UI, override the command:

```bash
docker run -v $(pwd):/data agent-arena evaluate --project projects/my_project
```

## Devcontainer / Codespaces

`.devcontainer/devcontainer.json` is in the repo. Opening it in VS Code or a
GitHub Codespace runs `pip install -e ".[dev]"` automatically and forwards
port 8420 for the UI.

## Extras

Provider SDKs are optional and import lazily. Install only what you call.

| Extra | Pulls in | For |
|---|---|---|
| *(none)* | pyyaml | Engine, CLI, UI, mock and local models |
| `[anthropic]` | `anthropic>=0.40` | Claude models |
| `[openai]` | `openai>=1.40` | GPT models |
| `[gemini]` | `google-generativeai>=0.8` | Gemini models |
| `[litellm]` | `litellm>=1.50` | Bedrock, Together, Azure, anything LiteLLM reaches |
| `[all]` | all four | |
| `[dev]` | `pytest>=8.0` | Contributing |

```bash
pip install -e ".[anthropic]"
pip install -e ".[all]"
pip install -e ".[dev]"
```

You do not need any of them to start: `mock:` and local models work with the base
install, and examples 1, 2 and 4 run fully offline.

If you call a model whose SDK is missing, the error names the exact fix:

```text
the 'anthropic' provider needs the 'anthropic' package:
pip install 'agent-arena[anthropic]'
```

## Verify

```bash
arena --version
arena scorers
arena evaluate --project projects/support_triage --quiet --no-report
```

The third proves the whole path works offline with no credential. If it produces
a leaderboard, the install is good.

## For contributing

```bash
pip install -e ".[dev]"
python3 -m pytest -q        # 715 passed in ~44s
```

Use a **fresh** virtualenv if you want to verify the stdlib-only invariant. An
environment where you previously installed a provider SDK will not prove it.

## The documentation site

```bash
pip install -r site/requirements.txt
python3 site/build.py
python3 -m http.server -d site/_build 8000
```

`site/requirements.txt` is build-time only. It is not a runtime dependency and
does not affect invariant 1.

## Uninstalling

```bash
pip uninstall agent-arena
```

Settings and any stored credentials live in `~/.config/agent-arena/`; delete that
directory to remove them. Project folders and their results are yours, and
nothing outside them is touched.
