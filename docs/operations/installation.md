# Installation

## Requirements

Python 3.10, 3.11, 3.12 or 3.13. CI tests all four.

## Install

The package is not yet on PyPI — the release workflow is configured but no
version has been tagged. Install from source:

```bash
git clone https://github.com/adityamhaske/agent-arena
cd agent-arena
pip install -e .
```

That gives you the engine and the CLI. One dependency: PyYAML, and even that is
optional — JSON config works without it.

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
install, and both example projects run offline.

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
python3 -m pytest -q        # 620 passed in ~30s
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
