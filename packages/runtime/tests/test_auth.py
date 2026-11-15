import asyncio
import json
import threading

import pytest

from lms_mcp.auth import AuthManager
from lms_mcp.browser import Browser
from lms_mcp.config import AuthRequired
from lms_mcp.session import parse_cookies


class FakeDriver:
    def __init__(self, cookies=None):
        self.cookies = cookies or [{"name": "session", "value": "browser-secret"}]
        self.current_url = "https://my.centraluniversity.ru/learn/"
        self.closed = False

    def get(self, _):
        pass

    def get_cookies(self):
        return self.cookies

    def quit(self):
        self.closed = True


@pytest.fixture(autouse=True)
def browser(monkeypatch):
    monkeypatch.setattr("lms_mcp.auth.select_browser", lambda _: Browser("chromium", "/browser", "chrome"))


async def test_browser_login_captures_only_after_api_validation(store):
    driver = FakeDriver()
    validated = []

    def probe(cookies):
        validated.append(cookies)
        return cookies

    auth = AuthManager(store, driver_factory=lambda _: driver, probe=probe)
    result = await auth.begin()
    assert result["state"] == "opening"
    await auth.flow.task
    assert validated
    assert auth.status()["login"]["state"] == "authenticated"
    assert store.get()[0]["value"] == "browser-secret"
    assert "browser-secret" not in json.dumps(auth.status())
    assert driver.closed


async def test_cancel_in_flight_probe_does_not_commit(store):
    entered, finish = threading.Event(), threading.Event()
    driver = FakeDriver()

    def probe(cookies):
        entered.set()
        finish.wait(5)
        return cookies

    auth = AuthManager(store, lambda _: driver, probe)
    await auth.begin()
    assert await asyncio.to_thread(entered.wait, 5)
    auth.cancel()
    finish.set()
    await auth.close()
    assert store.get()[0]["value"] == "test-secret"
    assert auth.status()["login"]["state"] == "cancelled"
    assert driver.closed


async def test_failed_import_does_not_replace_working_session(store):
    def probe(_):
        raise AuthRequired("invalid")

    auth = AuthManager(store, probe=probe)
    with pytest.raises(AuthRequired):
        await auth.import_cookies(parse_cookies("session=wrong"))
    assert store.get()[0]["value"] == "test-secret"


async def test_browser_errors_never_echo_details(store):
    def launch(_):
        raise RuntimeError("Cookie: session=TOP-SECRET")

    auth = AuthManager(store, driver_factory=launch)
    await auth.begin()
    await auth.flow.task
    assert auth.status()["login"]["state"] == "failed"
    assert "TOP-SECRET" not in json.dumps(auth.status())
