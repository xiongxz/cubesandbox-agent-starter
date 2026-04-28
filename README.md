# CubeSandbox Agent Starter

Minimal starter repository for building a CubeSandbox-compatible agent image.

Features:

- Fixed probe port: `49999`
- HTTP health endpoint: `GET /healthz`
- Session initialization endpoint: `POST /session/init`
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
