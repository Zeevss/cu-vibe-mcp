"""Opt-in test: a real Chromium logs in to a loopback fixture, never to the university."""

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lms_mcp.auth import AuthManager
from lms_mcp.browser import open_driver, select_browser
from lms_mcp.session import SessionStore


@pytest.mark.browser
@pytest.mark.skipif(os.environ.get("LMS_MCP_BROWSER_TEST") != "1", reason="opt-in real browser test")
async def test_real_browser_auto_selection_and_cookie_capture(monkeypatch, tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.path = self.path.partition("?")[0]
            if self.path == "/learn/":
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()
            elif self.path == "/login":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b'<form action="/complete"><button id="login">Fixture login</button></form>')
            elif self.path == "/complete":
                self.send_response(200)
                self.send_header("Set-Cookie", "fixture_session=dummy-local-cookie; Path=/; HttpOnly")
                self.end_headers()
                self.wfile.write(b"Signed in to the local fixture")
            elif self.path == "/api/micro-lms/students/me":
                assert self.headers.get("Cookie") == "fixture_session=dummy-local-cookie"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"lateDaysBalance": 24}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr("lms_mcp.auth.PORTAL", base)
    monkeypatch.setitem(__import__("lms_mcp.config", fromlist=["ORIGINS"]).ORIGINS, "lms", base)
    selected = select_browser("auto")
    monkeypatch.setattr("lms_mcp.auth.select_browser", lambda _: selected)

    class FixtureBrowser:
        def __init__(self):
            self.driver = open_driver(selected, headless=True)

        def get(self, url):
            assert url.startswith(base)
            self.driver.get(url)
            # Simulates the user's explicit click on our local test login, not a real credential form.
            self.driver.find_element("id", "login").click()

        def __getattr__(self, name):
            return getattr(self.driver, name)

    auth = AuthManager(SessionStore(tmp_path / "session"), driver_factory=lambda _: FixtureBrowser())
    try:
        await auth.begin(timeout_seconds=30)
        await asyncio.wait_for(asyncio.shield(auth.flow.task), 25)
        assert auth.status()["login"]["state"] == "authenticated", auth.status()
        assert auth.status()["login"]["browser"] == selected.name
        cookies = auth.store.get()
        assert cookies[0]["name"] == "fixture_session"
        assert cookies[0]["value"] == "dummy-local-cookie"
    finally:
        await auth.close()
        server.shutdown()
        server.server_close()
        thread.join(3)
