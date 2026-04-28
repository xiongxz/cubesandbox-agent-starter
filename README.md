# CubeSandbox Agent Starter

Minimal starter repository for building a CubeSandbox-compatible agent image.

Features:

- Fixed probe port: `49999`
- HTTP health endpoint: `GET /healthz`
- Startup-time identity memory loading from local Markdown files
- Optional manual rebind endpoint: `POST /session/init`
- Minimal chat endpoint: `POST /chat`
- OpenAI-compatible LLM configuration via environment variables
- `agent.build.yaml` contract for image platform automation

## Run locally

```bash
docker build -t cubesandbox-agent-starter:local .
docker run --rm -p 49999:49999 \
  -e AGENT_TENANT_ID="t1" \
  -e AGENT_USER_ID="u1" \
  -e AGENT_AGENT_ID="default-agent" \
  -e AGENT_SESSION_ID="boot-session" \
  cubesandbox-agent-starter:local
```

Health check:

```bash
curl http://localhost:49999/healthz
```

Chat without calling `/session/init` first:

```bash
curl -X POST http://localhost:49999/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Summarize what you know about me."}'
```

Optional manual session rebinding:

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

## Identity environment variables

These env vars are read at process startup and are used to preload the default session memory:

- `AGENT_TENANT_ID`
- `AGENT_USER_ID`
- `AGENT_AGENT_ID`
- `AGENT_SESSION_ID`

Example:

```bash
docker run --rm -p 49999:49999 \
  -e AGENT_TENANT_ID="t1" \
  -e AGENT_USER_ID="u1" \
  -e AGENT_AGENT_ID="default-agent" \
  -e AGENT_SESSION_ID="boot-session" \
  -e LLM_BASE_URL="https://api.openai.com/v1" \
  -e LLM_API_KEY="sk-..." \
  -e LLM_MODEL="gpt-4o-mini" \
  cubesandbox-agent-starter:local
```

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
