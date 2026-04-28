import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer


PORT = int(os.getenv("PORT", "49999"))


class Handler(BaseHTTPRequestHandler):
    def _write_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._write_json(200, {"status": "ok"})
            return

        self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/session/init":
            self._write_json(404, {"error": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._write_json(400, {"error": "invalid json"})
            return

        required = ["tenant_id", "user_id", "agent_id", "session_id"]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            self._write_json(400, {"error": "missing required fields", "fields": missing})
            return

        self._write_json(
            200,
            {
                "status": "initialized",
                "tenant_id": payload["tenant_id"],
                "user_id": payload["user_id"],
                "agent_id": payload["agent_id"],
                "session_id": payload["session_id"],
            },
        )

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
