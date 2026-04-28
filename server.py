import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer


PORT = int(os.getenv("PORT", "49999"))
MEMORY_DIR = os.getenv("MEMORY_DIR", "/app/memories")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SEC = int(os.getenv("LLM_TIMEOUT_SEC", "60"))
LLM_SYSTEM_PROMPT = os.getenv(
    "LLM_SYSTEM_PROMPT",
    "You are a helpful assistant running inside a CubeSandbox agent runtime.",
)

AGENT_TENANT_ID = os.getenv("AGENT_TENANT_ID", "")
AGENT_USER_ID = os.getenv("AGENT_USER_ID", "")
AGENT_AGENT_ID = os.getenv("AGENT_AGENT_ID", "default-agent")
AGENT_SESSION_ID = os.getenv("AGENT_SESSION_ID", "boot-session")


@dataclass
class SessionState:
    tenant_id: str
    user_id: str
    agent_id: str
    session_id: str
    memory_text: str
    memory_source: str

    @property
    def system_prompt(self) -> str:
        if self.memory_text:
            return (
                f"{LLM_SYSTEM_PROMPT}\n\n"
                "Use the following identity memory when answering.\n"
                f"{self.memory_text}"
            )
        return LLM_SYSTEM_PROMPT


SESSIONS: dict[str, SessionState] = {}


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


def ensure_boot_session() -> SessionState:
    existing = SESSIONS.get(AGENT_SESSION_ID)
    if existing is not None:
        return existing

    memory_text, source = load_memory_markdown(AGENT_TENANT_ID, AGENT_USER_ID, AGENT_AGENT_ID)
    state = SessionState(
        tenant_id=AGENT_TENANT_ID,
        user_id=AGENT_USER_ID,
        agent_id=AGENT_AGENT_ID,
        session_id=AGENT_SESSION_ID,
        memory_text=memory_text,
        memory_source=source,
    )
    SESSIONS[state.session_id] = state
    return state


def call_llm(state: SessionState, user_message: str) -> dict[str, str]:
    if not LLM_BASE_URL or not LLM_API_KEY:
        return {
            "mode": "fallback",
            "reply": (
                "LLM is not configured. Set LLM_BASE_URL and LLM_API_KEY to enable live chat.\n\n"
                f"Loaded memory source: {state.memory_source}\n\n"
                f"{state.memory_text or 'No memory content loaded.'}"
            ),
        }

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": state.system_prompt,
            },
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
    }

    request = urllib.request.Request(
        url=f"{LLM_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=LLM_TIMEOUT_SEC) as response:
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
            state = ensure_boot_session()
            self._write_json(
                200,
                {
                    "status": "ok",
                    "llm_configured": bool(LLM_BASE_URL and LLM_API_KEY),
                    "memory_dir": MEMORY_DIR,
                    "boot_session_id": state.session_id,
                    "memory_source": state.memory_source,
                },
            )
            return

        self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/session/init":
            self._handle_session_init()
            return
        if self.path == "/chat":
            self._handle_chat()
            return

        self._write_json(404, {"error": "not found"})

    def _handle_session_init(self) -> None:
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._write_json(400, {"error": "invalid json"})
            return

        required = ["tenant_id", "user_id", "agent_id", "session_id"]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            self._write_json(400, {"error": "missing required fields", "fields": missing})
            return

        memory_text, source = load_memory_markdown(
            payload["tenant_id"],
            payload["user_id"],
            payload["agent_id"],
        )
        state = SessionState(
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
            agent_id=payload["agent_id"],
            session_id=payload["session_id"],
            memory_text=memory_text,
            memory_source=source,
        )
        SESSIONS[state.session_id] = state

        self._write_json(
            200,
            {
                "status": "initialized",
                "tenant_id": state.tenant_id,
                "user_id": state.user_id,
                "agent_id": state.agent_id,
                "session_id": state.session_id,
                "memory_loaded": True,
                "memory_source": state.memory_source,
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

        session_id = payload.get("session_id") or AGENT_SESSION_ID
        state = SESSIONS.get(session_id)
        if state is None:
            state = ensure_boot_session()

        result = call_llm(state, str(message))
        self._write_json(
            200,
            {
                "status": "ok",
                "session_id": state.session_id,
                "tenant_id": state.tenant_id,
                "user_id": state.user_id,
                "agent_id": state.agent_id,
                "mode": result["mode"],
                "memory_source": state.memory_source,
                "reply": result["reply"],
            },
        )

    def log_message(self, format: str, *args) -> None:
        return


ensure_boot_session()


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
