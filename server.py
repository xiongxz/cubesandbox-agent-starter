import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


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


SESSIONS: dict[str, "SessionState"] = {}


@dataclass
class SessionState:
    tenant_id: str
    user_id: str
    agent_id: str
    session_id: str
    memory: dict[str, Any]


def load_memory(tenant_id: str, user_id: str, agent_id: str) -> tuple[dict[str, Any], str]:
    candidates = [
        os.path.join(MEMORY_DIR, tenant_id, user_id, f"{agent_id}.json"),
        os.path.join(MEMORY_DIR, tenant_id, f"{user_id}.json"),
        os.path.join(MEMORY_DIR, "default.json"),
    ]

    for path in candidates:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fp:
                return json.load(fp), path

    return {"profile": "", "preferences": [], "facts": []}, "generated-empty"


def summarize_memory(memory: dict[str, Any]) -> str:
    profile = memory.get("profile", "")
    preferences = memory.get("preferences", [])
    facts = memory.get("facts", [])

    lines = []
    if profile:
        lines.append(f"Profile: {profile}")
    if preferences:
        lines.append("Preferences:")
        lines.extend(f"- {item}" for item in preferences)
    if facts:
        lines.append("Facts:")
        lines.extend(f"- {item}" for item in facts)

    return "\n".join(lines).strip() or "No stored memory is available for this identity."


def extract_content(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts = []
        for item in message:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(part for part in parts if part).strip()
    return ""


def call_llm(memory_summary: str, user_message: str) -> dict[str, Any]:
    if not LLM_BASE_URL or not LLM_API_KEY:
        return {
            "mode": "fallback",
            "reply": (
                "LLM is not configured. Set LLM_BASE_URL and LLM_API_KEY to enable /chat.\n\n"
                f"Loaded memory summary:\n{memory_summary}"
            ),
        }

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"{LLM_SYSTEM_PROMPT}\n\n"
                    "Use the following identity memory when answering.\n"
                    f"{memory_summary}"
                ),
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
    content = extract_content(message.get("content"))
    if not content:
        content = "LLM response content was empty."

    return {"mode": "live", "reply": content}


class Handler(BaseHTTPRequestHandler):
    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._write_json(
                200,
                {
                    "status": "ok",
                    "llm_configured": bool(LLM_BASE_URL and LLM_API_KEY),
                    "memory_dir": MEMORY_DIR,
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

        memory, source = load_memory(payload["tenant_id"], payload["user_id"], payload["agent_id"])
        state = SessionState(
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
            agent_id=payload["agent_id"],
            session_id=payload["session_id"],
            memory=memory,
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
                "memory_source": source,
                "memory_summary": summarize_memory(memory),
            },
        )

    def _handle_chat(self) -> None:
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._write_json(400, {"error": "invalid json"})
            return

        session_id = payload.get("session_id")
        message = payload.get("message")
        if not session_id or not message:
            self._write_json(400, {"error": "session_id and message are required"})
            return

        state = SESSIONS.get(session_id)
        if state is None:
            self._write_json(
                404,
                {
                    "error": "session is not initialized",
                    "hint": "Call POST /session/init before POST /chat.",
                },
            )
            return

        memory_summary = summarize_memory(state.memory)
        llm_result = call_llm(memory_summary, str(message))

        self._write_json(
            200,
            {
                "status": "ok",
                "session_id": session_id,
                "mode": llm_result["mode"],
                "memory_summary": memory_summary,
                "reply": llm_result["reply"],
            },
        )

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
