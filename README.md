# CubeSandbox Agent Starter

Minimal starter repository for building a CubeSandbox-compatible agent image.

Features:

- CubeSandbox `envd` control plane on `:49983`
- Template probe endpoint: `GET /health -> 204`
- Agent app port on `:49999`
- Agent health endpoint: `GET /healthz -> 200`
- Startup-time fallback config from environment variables
- Runtime init endpoint: `POST /init`
- Compatibility alias: `POST /session/init`
- Minimal chat endpoint: `POST /chat`
- Minimal code execution endpoint: `POST /execute`
- OpenAI-compatible LLM configuration via environment variables
- `agent.build.yaml` contract for image platform automation

## Port layout

- `49983` is reserved for CubeSandbox `envd`
- `GET http://<host>:49983/health` must return `204`
- `49999` is the agent application's own HTTP port
- `GET http://<host>:49999/healthz` and `POST http://<host>:49999/chat` stay on the app side

Do not make the agent app itself listen on `49983`. That port is for `envd`, not for your business endpoints.

## Run locally

```bash
docker buildx build --platform linux/amd64 --load -t cubesandbox-agent-starter:local .
docker run --rm -p 49983:49983 -p 49999:49999 \
  -e AGENT_TENANT_ID="t1" \
  -e AGENT_USER_ID="u1" \
  -e AGENT_AGENT_ID="default-agent" \
  -e AGENT_SESSION_ID="boot-session" \
  cubesandbox-agent-starter:local
```

CubeSandbox probe check:

```bash
curl -i http://localhost:49983/health
```

Agent health check:

```bash
curl http://localhost:49999/healthz
```

Chat without calling `/init` first:

```bash
curl -X POST http://localhost:49999/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Summarize what you know about me."}'
```

Initialize runtime config from request body:

```bash
curl -X POST http://localhost:49999/init \
  -H 'Content-Type: application/json' \
  -d '{
    "tenant_id":"t2",
    "user_id":"u2",
    "agent_id":"default-agent",
    "session_id":"runtime-session",
    "llm": {
      "base_url":"https://api.openai.com/v1",
      "api_key":"sk-...",
      "model":"gpt-4o-mini"
    }
  }'
```

Chat after runtime init:

```bash
curl -X POST http://localhost:49999/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"请介绍一下你自己"}'
```

Execute Python code:

```bash
curl -X POST http://localhost:49999/execute \
  -H 'Content-Type: application/json' \
  -d '{"language":"python","code":"print(1 + 2)"}'
```

Execute shell code:

```bash
curl -X POST http://localhost:49999/execute \
  -H 'Content-Type: application/json' \
  -d '{"language":"shell","code":"pwd && ls -la","timeout_sec":10}'
```

Compatibility alias for older callers:

```bash
curl -X POST http://localhost:49999/session/init \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"t1","user_id":"u1","agent_id":"a1","session_id":"s1"}'
```

Chat with a specific session id:

```bash
curl -X POST http://localhost:49999/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"s1","message":"Summarize what you know about me."}'
```

## LLM environment variables

You can pass these env vars when the sandbox starts:

- `LLM_BASE_URL`
  Example: `https://api.openai.com/v1`
- `LLM_API_KEY`
- `LLM_MODEL`
  Default: `gpt-4o-mini`
- `LLM_TIMEOUT_SEC`
  Default: `60`
- `LLM_SYSTEM_PROMPT`
  Optional custom system prompt
- `EXEC_TIMEOUT_SEC`
  Default: `15`
- `EXEC_MAX_OUTPUT_CHARS`
  Default: `12000`
- `EXEC_WORKDIR`
  Default: `/tmp/agent-workspace`

## Identity environment variables

These env vars are only used as fallback/default mode when `/init` has not provided a runtime config yet:

- `AGENT_TENANT_ID`
- `AGENT_USER_ID`
- `AGENT_AGENT_ID`
- `AGENT_SESSION_ID`

Example:

```bash
docker run --rm -p 49983:49983 -p 49999:49999 \
  -e AGENT_TENANT_ID="t1" \
  -e AGENT_USER_ID="u1" \
  -e AGENT_AGENT_ID="default-agent" \
  -e AGENT_SESSION_ID="boot-session" \
  -e LLM_BASE_URL="https://api.openai.com/v1" \
  -e LLM_API_KEY="sk-..." \
  -e LLM_MODEL="gpt-4o-mini" \
  cubesandbox-agent-starter:local
```

## Runtime config model

- `/init` is the primary runtime bootstrap API.
- `/session/init` is a compatibility alias that calls the same logic.
- `/chat` prefers the active runtime config loaded by `/init`.
- If no runtime config has been loaded, `/chat` falls back to environment-variable defaults.
- If `/chat` is called with a specific `session_id`, that session must already have been initialized.

## Memory loading

The starter loads memory from Markdown files in this order:

1. `/app/memories/<tenant_id>/<user_id>/<agent_id>.md`
2. `/app/memories/<tenant_id>/<user_id>.md`
3. `/app/memories/default.md`

If nothing matches, it falls back to `default.md`.

This repository already includes concrete identity memory examples:

- `tenant_id=t1`
- `user_id=u1`
- `tenant_id=t2`
- `user_id=u2`

## CubeSandbox template parameters

When creating a template from this image, use the CubeSandbox control plane port for probing:

```bash
cubemastercli tpl create-from-image \
  --image <your-image-ref> \
  --writable-layer-size 1G \
  --expose-port 49983 \
  --expose-port 49999 \
  --probe 49983 \
  --probe-path /health
```
