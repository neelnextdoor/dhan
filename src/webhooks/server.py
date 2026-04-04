from __future__ import annotations

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from src.core.config import AppConfig
from src.core.logger import get_logger
from src.webhooks.handler import WebhookHandler

logger = get_logger("webhook_server")


class _PostbackRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler that receives Dhan postback POSTs and feeds them to the WebhookHandler."""

    webhook_handler: WebhookHandler = None  # set by WebhookServer before starting
    auth_token: str = ""  # optional verification token

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._respond(400, {"error": "empty body"})
            return

        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in postback: %s", raw[:200])
            self._respond(400, {"error": "invalid json"})
            return

        if self.auth_token:
            header_token = self.headers.get("X-Webhook-Token", "")
            if header_token != self.auth_token:
                logger.warning("Unauthorized postback attempt (bad token)")
                self._respond(401, {"error": "unauthorized"})
                return

        if self.webhook_handler:
            update = self.webhook_handler.process(payload)
            if update:
                self._respond(200, {"status": "ok", "orderId": update.order_id})
            else:
                self._respond(422, {"status": "parse_error"})
        else:
            self._respond(503, {"error": "handler not ready"})

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, {"status": "healthy", "service": "dhan_algo_webhook"})
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, status: int, body: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format: str, *args: Any) -> None:
        # Route HTTP access logs through our logger instead of stderr
        logger.debug("HTTP %s", format % args)


class WebhookServer:
    """
    Runs the postback HTTP server in a background thread.

    Usage:
        handler = WebhookHandler()
        server = WebhookServer(config, handler)
        server.start()  # non-blocking, runs in daemon thread
        # ... later ...
        server.stop()
    """

    def __init__(self, config: AppConfig, handler: WebhookHandler):
        self.config = config
        self.handler = handler
        self._host = config.webhook.host
        self._port = config.webhook.port
        self._auth_token = config.webhook.auth_token
        self._httpd: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        _PostbackRequestHandler.webhook_handler = self.handler
        _PostbackRequestHandler.auth_token = self._auth_token

        self._httpd = HTTPServer((self._host, self._port), _PostbackRequestHandler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="webhook-server",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Webhook server started on %s:%d (path: /)",
            self._host, self._port,
        )

    def stop(self) -> None:
        if self._httpd:
            logger.info("Stopping webhook server")
            self._httpd.shutdown()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}/"
