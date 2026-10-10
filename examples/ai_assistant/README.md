# AI assistant

An assistant wired through a plugin, dependency injection, the HTTP adapter, and a workflow. It runs
entirely against the deterministic fake provider, so nothing here needs a model, a service, or a
network.

```powershell
cd examples
python -m ai_assistant.app
```

## Routes

| Route | What it shows |
| --- | --- |
| `GET /health` | the provider's readiness, including the model identity and any capability mismatch |
| `POST /ask` | structured output: the response is validated against a declared JSON Schema before the route sees it |
| `POST /research` | a bounded tool loop: the model asks for `knowledge`, the allowlist validates the arguments, and the answer comes back with usage |
| `POST /triage` | a workflow whose steps call the model: `classify` retries transient AI failures, `answer` has its own timeout |

```powershell
$body = '{"question": "Will it rain?"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/ask -Method Post -ContentType application/json -Body $body
```

## The Ollama profile

The default `provider = "fake"` profile is what CI exercises. To use a local Ollama service, install
the extra, pull a model yourself, and select the profile explicitly:

```powershell
python -m pip install -e ".[ollama,http]"
ollama pull llama3.2
$env:XYBEROS_AI__OLLAMA__MODEL = "llama3.2"
$env:XYBEROS_AI__OLLAMA__STRUCTURED_OUTPUT = "true"
```

```python
from ai_assistant.app import build_asgi_app, create_app

app = create_app({"provider": "ollama", "model": "llama3.2", "structured_output": True})
asgi_app = build_asgi_app(app)
```

Xyberos never pulls, starts, stops, or upgrades a model, so pointing the example at a service without
the model already present fails with an actionable error instead of downloading anything.

## What to read next

- [the AI guide](../../docs/ai.md) documents the contracts, the capability policy, the schema subset,
  and the security and operations rules;
- [the workflow guide](../../docs/workflow.md) explains the retry, deadline, and cancellation
  semantics the `triage` workflow relies on.
