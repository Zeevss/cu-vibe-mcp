import json
import os
import time

import pytest

from lms_mcp.config import LMSError
from lms_mcp.session import SessionStore, cookie_jar, normalize_cookies, parse_cookies


def test_cookie_header_chunks_and_equals():
    cookies = parse_cookies(
        "Cookie: .AspNetCore.Cookies=chunks-2; .AspNetCore.CookiesC1=a==; .AspNetCore.CookiesC2=b"
    )
    assert len(cookies) == 3
    assert cookies[1]["value"] == "a=="


def test_cookie_formats_and_scope():
    raw = {
        "cookies": [
            {"name": "s", "value": "valid", "domain": ".centraluniversity.ru", "path": "/"},
            {"name": "other", "value": "no", "domain": "unrelated.example", "path": "/"},
        ]
    }
    cookies = parse_cookies(json.dumps(raw))
    assert len(cookies) == 1
    jar = cookie_jar(cookies, "lms")
    assert list(jar.jar)[0].domain == "my.centraluniversity.ru"
    text = "# Netscape HTTP Cookie File\n#HttpOnly_.centraluniversity.ru\tTRUE\t/\tTRUE\t0\ts\tv"
    assert parse_cookies(text)[0]["value"] == "v"


@pytest.mark.parametrize(
    "text",
    ["", "bad", "s=a\nInjected:secret", "{broken", "[1]", '[{"name":"a","value":"x","expires":"NaN"}]'],
)
def test_bad_cookies_are_rejected_without_echo(text):
    with pytest.raises(LMSError) as result:
        parse_cookies(text)
    assert "Injected" not in str(result.value)


def test_expired_cookie_is_not_reused(store):
    data = json.loads(store.path.read_text())
    data["services"]["lms"]["cookies"][0]["expires"] = time.time() - 1
    store.path.write_text(json.dumps(data))
    assert store.get() == []


def test_permissions_and_separate_services(store):
    store.put(parse_cookies("note=note-secret", "note"), "note")
    store.clear("lms")
    assert not store.get()
    assert store.get("note")[0]["value"] == "note-secret"
    assert "note-secret" not in json.dumps(store.status("note"))
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert store.root.stat().st_mode & 0o777 == 0o700


def test_wrong_domain_and_expiration():
    with pytest.raises(LMSError):
        normalize_cookies([{"name": "x", "value": "y", "domain": "note.cu.ru"}], "lms")
    with pytest.raises(LMSError):
        normalize_cookies([{"name": "x", "value": "y", "expires": time.time() - 1}], "lms")


def test_corrupt_file_is_actionable(tmp_path):
    store = SessionStore(tmp_path)
    store.path.write_text("[]")
    with pytest.raises(LMSError):
        store.get()


def test_inflight_rotation_cannot_overwrite_new_login(store):
    old = store.get()
    fresh = parse_cookies("session=fresh-login")
    store.put(fresh)
    store.rotate(old, parse_cookies("session=old-request-rotation"))
    assert store.get()[0]["value"] == "fresh-login"


def test_logout_recovers_from_corruption(tmp_path):
    store = SessionStore(tmp_path)
    store.path.write_text("broken")
    store.clear()
    store.put(parse_cookies("session=recovered"))
    assert store.get()[0]["value"] == "recovered"
