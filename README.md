# CubeSandbox Agent Starter

Minimal starter repository for building a CubeSandbox-compatible agent image.

Features:

- Fixed probe port: `49999`
- HTTP health endpoint: `GET /healthz`
- Session initialization endpoint: `POST /session/init`
- File-backed identity memory loading
- Minimal chat endpoint: `POST /chat`
- OpenAI-compatible LLM configuration via environment variables
- `agent.build.yaml` contract for image platform automation

## Run locally

```bash
docker build -t cubesandbox-agent-starter:local .
docker run --rm -p 49999:49999 cubesandbox-agent-starter:local
```

Health check:

```bash
curl http://localhost:49999/healthz
```

Session init:

```bash
curl -X POST http://localhost:49999/session/init \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"t1","user_id":"u1","agent_id":"a1","session_id":"s1"}'
```

Chat:

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

Example:

```bash
docker run --rm -p 49999:49999 \
  -e LLM_BASE_URL="https://api.openai.com/v1" \
  -e LLM_API_KEY="sk-..." \
  -e LLM_MODEL="gpt-4o-mini" \
  cubesandbox-agent-starter:local
```

## Memory loading

The starter loads memory from JSON files in this order:

1. `/app/memories/<tenant_id>/<user_id>/<agent_id>.json`
2. `/app/memories/<tenant_id>/<user_id>.json`
3. `/app/memories/default.json`

If nothing matches, it falls back to an empty generated memory object.

This repository already includes a concrete identity memory example:

- `tenant_id=t1`
- `user_id=u1`
- `agent_id=a1`
