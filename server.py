import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer


PORT = int(os.getenv("PORT", "49999"))
MEMORY_DIR = os.getenv("MEMORY_DIR", "/app/memories")
EXEC_WORKDIR = os.getenv("EXEC_WORKDIR", "/tmp/agent-workspace")

os.makedirs(EXEC_WORKDIR, exist_ok=True)


def clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def normalize_str(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def get_env_defaults() -> dict[str, object]:
    return {
        "llm_base_url": os.getenv("LLM_BASE_URL", "").rstrip("/"),
        "llm_api_key": os.getenv("LLM_API_KEY", ""),
        "llm_model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
        "llm_timeout_sec": clamp_int(os.getenv("LLM_TIMEOUT_SEC", "60"), default=60, minimum=1, maximum=300),
        "llm_system_prompt": os.getenv(
            "LLM_SYSTEM_PROMPT",
            "You are a helpful assistant running inside a CubeSandbox agent runtime.",
        ),
        "agent_tenant_id": os.getenv("AGENT_TENANT_ID", ""),
        "agent_user_id": os.getenv("AGENT_USER_ID", ""),
        "agent_agent_id": os.getenv("AGENT_AGENT_ID", "default-agent"),
        "agent_session_id": os.getenv("AGENT_SESSION_ID", "boot-session"),
        "exec_timeout_sec": clamp_int(os.getenv("EXEC_TIMEOUT_SEC", "15"), default=15, minimum=1, maximum=120),
        "exec_max_output_chars": clamp_int(
            os.getenv("EXEC_MAX_OUTPUT_CHARS", "12000"),
            default=12000,
            minimum=256,
            maximum=100000,
        ),
    }


@dataclass
class RuntimeConfig:
    tenant_id: str
    user_id: str
    agent_id: str
    session_id: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_sec: int
    llm_system_prompt: str
    memory_text: str
    memory_source: str
    config_source: str

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)

    @property
    def system_prompt(self) -> str:
        if self.memory_text:
            return (
                f"{self.llm_system_prompt}\n\n"
                "Use the following identity memory when answering.\n"
                f"{self.memory_text}"
            )
        return self.llm_system_prompt


RUNTIME_CONFIGS: dict[str, RuntimeConfig] = {}
ACTIVE_SESSION_ID = str(get_env_defaults()["agent_session_id"])


def load_memory_markdown(tenant_id: str, user_id: str, agent_id: str) -> tuple[str, str]:
    candidates = []
    if tenant_id and user_id and agent_id:
        candidates.append(os.path.join(MEMORY_DIR, tenant_id, user_id, f"{agent_id}.md"))
    if tenant_id and user_id:
        candidates.append(os.path.join(MEMORY_DIR, tenant_id, f"{user_id}.md"))
    candidates.append(os.path.join(MEMORY_DIR, "default.md"))

    for path in candidates:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fp:
                return fp.read().strip(), path

    return "", "generated-empty"


def build_boot_config() -> RuntimeConfig:
    env = get_env_defaults()
    memory_text, memory_source = load_memory_markdown(
        normalize_str(env["agent_tenant_id"]),
        normalize_str(env["agent_user_id"]),
        normalize_str(env["agent_agent_id"]),
    )
    return RuntimeConfig(
        tenant_id=normalize_str(env["agent_tenant_id"]),
        user_id=normalize_str(env["agent_user_id"]),
        agent_id=normalize_str(env["agent_agent_id"]),
        session_id=normalize_str(env["agent_session_id"]),
        llm_base_url=normalize_str(env["llm_base_url"]),
        llm_api_key=normalize_str(env["llm_api_key"]),
        llm_model=normalize_str(env["llm_model"], "gpt-4o-mini"),
        llm_timeout_sec=int(env["llm_timeout_sec"]),
        llm_system_prompt=normalize_str(env["llm_system_prompt"]),
        memory_text=memory_text,
        memory_source=memory_source,
        config_source="env-default",
    )


def ensure_boot_config() -> RuntimeConfig:
    boot_config = build_boot_config()
    existing = RUNTIME_CONFIGS.get(boot_config.session_id)
    if existing is not None:
        return existing
    RUNTIME_CONFIGS[boot_config.session_id] = boot_config
    return boot_config


def resolve_runtime_config(session_id: str | None = None) -> RuntimeConfig | None:
    if session_id:
        existing = RUNTIME_CONFIGS.get(session_id)
        if existing is not None:
            return existing
        boot_config = ensure_boot_config()
        if session_id == boot_config.session_id:
            return boot_config
        return None

    active = RUNTIME_CONFIGS.get(ACTIVE_SESSION_ID)
    if active is not None:
        return active
    return ensure_boot_config()


def build_runtime_config_from_payload(payload: dict, source: str) -> RuntimeConfig:
    base = resolve_runtime_config()
    assert base is not None

    llm_payload = payload.get("llm")
    if not isinstance(llm_payload, dict):
        llm_payload = {}

    memory_payload = payload.get("memory")
    if not isinstance(memory_payload, dict):
        memory_payload = {}

    tenant_id = normalize_str(payload.get("tenant_id"), base.tenant_id)
    user_id = normalize_str(payload.get("user_id"), base.user_id)
    agent_id = normalize_str(payload.get("agent_id"), base.agent_id)
    session_id = normalize_str(payload.get("session_id"), base.session_id)

    llm_base_url = normalize_str(
        llm_payload.get("base_url", payload.get("llm_base_url", base.llm_base_url)),
        base.llm_base_url,
    ).rstrip("/")
    llm_api_key = normalize_str(
        llm_payload.get("api_key", payload.get("llm_api_key", base.llm_api_key)),
        base.llm_api_key,
    )
    llm_model = normalize_str(
        llm_payload.get("model", payload.get("llm_model", base.llm_model)),
        base.llm_model,
    )
    llm_timeout_sec = clamp_int(
        llm_payload.get("timeout_sec", payload.get("llm_timeout_sec", base.llm_timeout_sec)),
        default=base.llm_timeout_sec,
        minimum=1,
        maximum=300,
    )
    llm_system_prompt = normalize_str(
        llm_payload.get("system_prompt", payload.get("llm_system_prompt", base.llm_system_prompt)),
        base.llm_system_prompt,
    )

    memory_override = memory_payload.get("markdown", payload.get("memory_markdown"))
    if memory_override is not None:
        memory_text = normalize_str(memory_override).strip()
        memory_source = normalize_str(memory_payload.get("source"), "request.memory_markdown")
    else:
        memory_text, memory_source = load_memory_markdown(tenant_id, user_id, agent_id)

    return RuntimeConfig(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        session_id=session_id,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        llm_timeout_sec=llm_timeout_sec,
        llm_system_prompt=llm_system_prompt,
        memory_text=memory_text,
        memory_source=memory_source,
        config_source=source,
    )


def persist_runtime_config(config: RuntimeConfig) -> RuntimeConfig:
    global ACTIVE_SESSION_ID
    RUNTIME_CONFIGS[config.session_id] = config
    ACTIVE_SESSION_ID = config.session_id
    return config


def runtime_config_summary(config: RuntimeConfig) -> dict[str, object]:
    return {
        "session_id": config.session_id,
        "tenant_id": config.tenant_id,
        "user_id": config.user_id,
        "agent_id": config.agent_id,
        "llm_configured": config.llm_configured,
        "llm_base_url_present": bool(config.llm_base_url),
        "llm_api_key_present": bool(config.llm_api_key),
        "llm_model": config.llm_model,
        "memory_source": config.memory_source,
        "config_source": config.config_source,
    }


def call_llm(config: RuntimeConfig, user_message: str) -> dict[str, str]:
    if not config.llm_configured:
        return {
            "mode": "fallback",
            "reply": (
                "LLM is not configured. Call /init or set env defaults to enable live chat.\n\n"
                f"Loaded memory source: {config.memory_source}\n\n"
                f"{config.memory_text or 'No memory content loaded.'}"
            ),
        }

    payload = {
        "model": config.llm_model,
        "messages": [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
    }

    request = urllib.request.Request(
        url=f"{config.llm_base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.llm_api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config.llm_timeout_sec) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"mode": "error", "reply": f"LLM request failed with HTTP {exc.code}: {detail}"}
    except urllib.error.URLError as exc:
        return {"mode": "error", "reply": f"LLM request failed: {exc.reason}"}

    choices = body.get("choices", [])
    if not choices:
        return {"mode": "error", "reply": "LLM response did not include any choices."}

    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        content = "\n".join(part for part in parts if part).strip()

    if not content:
        content = "LLM response content was empty."

    return {"mode": "live", "reply": str(content)}


def truncate_output(value: str) -> str:
    max_output_chars = int(get_env_defaults()["exec_max_output_chars"])
    if len(value) <= max_output_chars:
        return value
    return value[:max_output_chars] + "\n...[truncated]..."


def run_exec(language: str, code: str, timeout_sec: int) -> dict[str, object]:
    language = language.lower().strip()
    if language == "python":
        cmd = ["python3", "-c", code]
    elif language in {"shell", "bash", "sh"}:
        cmd = ["sh", "-lc", code]
    else:
        return {
            "status": "error",
            "error": "unsupported language",
            "supported_languages": ["python", "shell"],
        }

    started_at = time.time()
    try:
        completed = subprocess.run(
            cmd,
            cwd=EXEC_WORKDIR,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.time() - started_at) * 1000)
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace")
        return {
            "status": "ok",
            "language": language,
            "exit_code": None,
            "timed_out": True,
            "timeout_sec": timeout_sec,
            "duration_ms": duration_ms,
            "stdout": truncate_output(stdout),
            "stderr": truncate_output(stderr),
            "workdir": EXEC_WORKDIR,
        }

    duration_ms = int((time.time() - started_at) * 1000)
    return {
        "status": "ok",
        "language": language,
        "exit_code": completed.returncode,
        "timed_out": False,
        "timeout_sec": timeout_sec,
        "duration_ms": duration_ms,
        "stdout": truncate_output(completed.stdout),
        "stderr": truncate_output(completed.stderr),
        "workdir": EXEC_WORKDIR,
    }


class Handler(BaseHTTPRequestHandler):
    def _read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _write_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            config = resolve_runtime_config()
            assert config is not None
            self._write_json(
                200,
                {
                    "status": "ok",
                    "memory_dir": MEMORY_DIR,
                    "active_session_id": ACTIVE_SESSION_ID,
                    **runtime_config_summary(config),
                },
            )
            return

        self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/init":
            self._handle_init("request.init")
            return
        if self.path == "/session/init":
            self._handle_init("request.session_init")
            return
        if self.path == "/chat":
            self._handle_chat()
            return
        if self.path == "/execute":
            self._handle_exec()
            return

        self._write_json(404, {"error": "not found"})

    def _handle_init(self, source: str) -> None:
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._write_json(400, {"error": "invalid json"})
            return

        if not isinstance(payload, dict):
            self._write_json(400, {"error": "request body must be a JSON object"})
            return

        config = persist_runtime_config(build_runtime_config_from_payload(payload, source))
        self._write_json(
            200,
            {
                "status": "initialized",
                "active_session_id": ACTIVE_SESSION_ID,
                **runtime_config_summary(config),
            },
        )

    def _handle_chat(self) -> None:
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._write_json(400, {"error": "invalid json"})
            return

        message = payload.get("message")
        if not message:
            self._write_json(400, {"error": "message is required"})
            return

        requested_session_id = normalize_str(payload.get("session_id"), "")
        if requested_session_id:
            config = resolve_runtime_config(requested_session_id)
            if config is None:
                self._write_json(404, {"error": "session not initialized", "session_id": requested_session_id})
                return
        else:
            config = resolve_runtime_config()
            assert config is not None

        result = call_llm(config, str(message))
        self._write_json(
            200,
            {
                "status": "ok",
                "active_session_id": ACTIVE_SESSION_ID,
                "mode": result["mode"],
                "reply": result["reply"],
                **runtime_config_summary(config),
            },
        )

    def _handle_exec(self) -> None:
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._write_json(400, {"error": "invalid json"})
            return

        code = payload.get("code")
        if not code or not isinstance(code, str):
            self._write_json(400, {"error": "code is required"})
            return

        language = payload.get("language", "python")
        default_timeout = int(get_env_defaults()["exec_timeout_sec"])
        timeout_sec = clamp_int(payload.get("timeout_sec"), default=default_timeout, minimum=1, maximum=120)
        result = run_exec(language, code, timeout_sec)

        if result.get("status") == "error":
            self._write_json(400, result)
            return

        self._write_json(200, result)

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    ensure_boot_config()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
