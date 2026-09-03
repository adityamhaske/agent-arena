# Local models

Anything with an OpenAI-compatible endpoint sits in the same run as a frontier
API model: Ollama, LM Studio, vLLM, llama.cpp.

The local connector is built on `urllib` from the standard library — evaluating a
model on your own laptop requires no SDK at all.

## The short version

```yaml
models:
  - key: llama32
    model: llama3.2                     # provider inferred: local

  - key: qwen
    model: ollama/qwen2.5-coder:7b      # explicit prefix also works

  - key: lmstudio
    model: local/my-model
    api_base: http://localhost:1234/v1  # any OpenAI-compatible server

  - key: cloud_baseline
    model: claude-haiku-4-5             # competes in the same run
```

Default endpoint is Ollama's `http://localhost:11434/v1`. Point `api_base` at
anything speaking `POST /v1/chat/completions`.

## How a bare name resolves

`registry.infer_provider` routes to the local connector for:

- explicit prefixes — `ollama/`, `local/`, `lmstudio/`, `llamacpp/`, `vllm/`
- bare names starting `llama`, `qwen`, `mistral`, `mixtral`, `phi`, `gemma`,
  `deepseek`, `codellama`
- **any model with an `api_base` set** — giving a URL is itself the answer: it is
  an OpenAI-compatible server and the model name can be anything

## By runtime

### Ollama

```bash
ollama serve
ollama pull llama3.2
```

```yaml
models:
  - key: llama32
    model: llama3.2
```

### LM Studio

Start the local server (default port 1234).

```yaml
models:
  - key: lmstudio
    model: local/your-loaded-model
    api_base: http://localhost:1234/v1
```

### vLLM

```bash
python -m vllm.entrypoints.openai.api_server --model meta-llama/Llama-3.1-8B-Instruct
```

```yaml
models:
  - key: vllm_llama
    model: meta-llama/Llama-3.1-8B-Instruct
    api_base: http://localhost:8000/v1
```

### llama.cpp

```bash
./llama-server -m model.gguf --port 8080
```

```yaml
models:
  - key: llamacpp
    model: llamacpp/local
    api_base: http://localhost:8080/v1
```

## Cost

Local models are priced at zero in the shipped catalog. That is accurate for API
spend and misleading for total cost — electricity, hardware and your own time are
real. If you want a like-for-like comparison, put an estimate in a `card:`
override:

```yaml
models:
  - key: llama32
    model: llama3.2
    card: {input_usd_per_mtok: 0.05, output_usd_per_mtok: 0.05}   # your estimate
```

Note this is *your* number, not a sourced list price. The catalog will not invent
one for you; overriding it is a deliberate act.

## Latency is a real difference

Local models are frequently slower than a hosted frontier model, especially on
first token. If latency matters, set a target and let the leaderboard weigh it:

```yaml
metrics:
  weights: {accuracy: 0.5, cost: 0.2, latency: 0.3}
  latency: {target_ms: 2000}
constraints:
  max_latency_p95_ms: 8000
```

## Testing without a model installed

`demo/fake_local_server.py` speaks the OpenAI-compatible API, so the local path
can be exercised with nothing downloaded:

```bash
python demo/fake_local_server.py --port 11434 &
arena validate --project projects/local_demo
arena evaluate --project projects/local_demo --trials 1
```

CI runs exactly this, so the local code path is tested for real — sockets, HTTP,
JSON parsing — on every commit.

`projects/local_demo/` is the worked example; [../../demo.md](../../demo.md) is
the full walkthrough with real output.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Connection refused | Runtime not started | `ollama serve`, or start your server |
| 404 on the endpoint | Wrong base path | `api_base` must end at `/v1`, not `/v1/chat/completions` |
| Model not found | Not pulled | `ollama pull <model>` |
| Very high latency | Model loading on first call | Warm it with one request before timing |
| Timeouts | Large model, small timeout | Raise `run.timeout_s` |
