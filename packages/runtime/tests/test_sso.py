import getpass
import json
import time
import warnings
from urllib.parse import parse_qs

import httpx
import pytest
from filelock import FileLock

from lms_mcp.config import AuthRequired, LMSError
from lms_mcp.sso import CALLBACK, IDP, REALM, SSOClient, SSOError, hidden_input, interactive_login, parse_page

ACTION = IDP + REALM + "login-actions/authenticate?session_code=fixture&amp;execution=1"


def page(kind, *, error="", action=ACTION, extra=""):
    # Mirrors the observed theme: literal objects followed by per-template assignments.
    return f'''<script>window.authConfiguration = {{
      urls: {{loginUrl: window.location.origin + '/unused'}},
      currentState: {{userName: "student@example.test", selectedCredential: "credential", phoneNumber: "79990000000"}},
      messages: {{userName: "", systemMessage: {{level: "{"error" if error else ""}", content: {json.dumps(error)}}}}}}};</script>
      <script>window.authConfiguration.currentState.activePage = '{kind}';</script>
      <script>window.authConfiguration.urls.loginAction = {json.dumps(action)};{extra}</script>'''


def response(kind, **kwargs):
    return httpx.Response(200, text=page(kind, **kwargs))


def test_parse_real_theme_shape_and_entities():
    p = parse_page(
        page(
            "password",
            error="Неверный пароль",
            extra='window.authConfiguration.currentState.userName = "updated@example.test";',
        )
    )
    assert p.username == "updated@example.test"
    assert p.error
    assert "&execution=1" in p.action and "&amp;" not in p.action
    assert "student" not in repr(p) and "fixture" not in repr(p)


@pytest.mark.parametrize(
    "kind",
    [
        "updatePassword",
        "resetPassword",
        "verifyEmail",
        "otpConfigure",
        "recoveryLinkSent",
        "registration",
        "unexpected",
    ],
)
def test_required_actions_do_not_submit(kind):
    with pytest.raises(SSOError):
        parse_page(page(kind))


def test_captcha_and_account_lock():
    with pytest.raises(SSOError) as exc:
        parse_page(page("otp", extra="window.authConfiguration.currentState.recaptchaEnabled = true;"))
    assert exc.value.state == "captcha_required"
    with pytest.raises(SSOError) as exc:
        parse_page(page("password", error="Account temporarily disabled"))
    assert exc.value.state == "account_unavailable"


@pytest.mark.parametrize(
    "action",
    [
        "https://evil.test/login",
        "http://id.centraluniversity.ru/login",
        IDP + REALM + "login-actions/reset-credentials",
        "https://id.centraluniversity.ru@evil.test/login",
    ],
)
def test_unknown_form_destination_rejected(action):
    with pytest.raises(SSOError):
        parse_page(page("password", action=action))


def test_full_flow_wrong_password_wrong_otp_resend_callback_and_commit(store):
    posts = []
    state = ""

    def handle(request):
        nonlocal state
        if request.url.path.endswith("/auth"):
            state = request.url.params["state"]
            assert request.url.params["client_id"] == "api-gateway"
            return response("emailLogin")
        if request.method == "POST":
            posts.append(parse_qs(request.content.decode(), keep_blank_values=True))
            steps = [
                response("password"),
                response("password", error="Неверный пароль"),
                response("otpEmail"),
                response("otpEmail", error="Код истёк"),
                response("otpEmail"),
            ]
            if len(posts) <= len(steps):
                assert store.get()[0]["value"] == "test-secret"
                return steps[len(posts) - 1]
            return httpx.Response(302, headers={"location": CALLBACK + "?code=fixture&state=" + state})
        assert str(request.url).startswith(CALLBACK)
        return (
            httpx.Response(
                302,
                headers={
                    "set-cookie": "session=fixture-new; Secure; HttpOnly; Path=/",
                    "location": "/learn/",
                },
            )
            if request.url.path.endswith("/callback")
            else httpx.Response(200)
        )

    # Callback redirects to portal SPA; API validation is independent of HTML success.
    def transport(request):
        if request.url.path == "/learn/":
            return httpx.Response(200, text="portal")
        return handle(request)

    probed = []

    def probe(cookies):
        probed.extend(cookies)
        return cookies

    client = SSOClient(store, transport=httpx.MockTransport(transport), probe=probe)
    try:
        assert client.start() == "emailLogin"
        assert client.submit("student@example.test") == "password"
        assert client.submit("wrong-password") == "password"
        assert client.page.error
        assert client.submit("right-password") == "otpEmail"
        assert client.submit("000000") == "otpEmail"
        assert client.page.error
        assert client.submit("", resend=True) == "otpEmail"
        assert client.submit("123456") == "authenticated"
        assert posts == [
            {"username": ["student@example.test"]},
            {"password": ["wrong-password"]},
            {"password": ["right-password"]},
            {"otp": ["000000"], "submit": ["submit"]},
            {"otp": [""], "resend": ["resend"]},
            {"otp": ["123456"], "submit": ["submit"]},
        ]
        assert probed[0]["value"] == "fixture-new"
        assert store.get()[0]["value"] == "fixture-new"
    finally:
        client.close()
    assert not list(client.client.cookies.jar)


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("passwordLogin", "pw", {"username": ["u"], "password": ["pw"], "credentialId": ["credential"]}),
        (
            "otp",
            "123456",
            {
                "action": ["verify"],
                "phoneNumber": ["79990000000"],
                "code": ["123456"],
                "credentialId": ["credential"],
            },
        ),
    ],
)
def test_other_form_payloads(store, kind, value, expected):
    def handle(request):
        if request.method == "POST":
            assert parse_qs(request.content.decode()) == expected
        return response(kind)

    client = SSOClient(store, transport=httpx.MockTransport(handle))
    try:
        client.start()
        client.submit(value, username="u")
    finally:
        client.close()


@pytest.mark.parametrize(
    "status,location", [(302, "https://evil.test"), (307, CALLBACK), (302, CALLBACK + "?code=x&state=wrong")]
)
def test_redirects_never_forward_secrets(store, status, location):
    requests = []

    def handle(request):
        requests.append(request)
        return (
            response("password")
            if request.method == "GET"
            else httpx.Response(status, headers={"location": location})
        )

    client = SSOClient(store, transport=httpx.MockTransport(handle))
    try:
        client.start()
        with pytest.raises(SSOError):
            client.submit("TOP-SECRET")
        assert len(requests) == 2
        assert store.get()[0]["value"] == "test-secret"
    finally:
        client.close()


@pytest.mark.parametrize("mode", ["timeout", "429", "oversize", "loop", "probe"])
def test_failed_login_preserves_session_and_sanitizes_errors(store, mode):
    client = None

    def handle(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("TOP-SECRET", request=request)
        if mode == "429":
            return httpx.Response(429, text="TOP-SECRET")
        if mode == "oversize":
            return httpx.Response(200, content=b"x" * (1024 * 1024 + 1))
        if mode == "loop":
            return httpx.Response(302, headers={"location": str(request.url)})
        if request.url.host == "id.centraluniversity.ru":
            return httpx.Response(302, headers={"location": CALLBACK + "?code=x&state=" + client.state})
        return httpx.Response(200, headers={"set-cookie": "session=fixture; Path=/; Secure"})

    def probe(_):
        raise AuthRequired("Сессия не принята")

    client = SSOClient(store, transport=httpx.MockTransport(handle), probe=probe)
    try:
        with pytest.raises(LMSError) as exc:
            client.start()
        assert "TOP-SECRET" not in str(exc.value)
        assert store.get()[0]["value"] == "test-secret"
    finally:
        client.close()


def test_expired_flow_does_not_send_password(store):
    calls = []

    def handle(request):
        calls.append(request)
        return response("password")

    client = SSOClient(store, transport=httpx.MockTransport(handle))
    try:
        client.start()
        client.deadline = time.monotonic() - 1
        with pytest.raises(SSOError, match="истёк"):
            client.submit("TOP-SECRET")
        assert len(calls) == 1
    finally:
        client.close()


def test_hidden_input_never_falls_back_to_echo(monkeypatch):
    def fallback(_):
        warnings.warn("cannot hide", getpass.GetPassWarning)
        pytest.fail("echoing fallback must not run")

    monkeypatch.setattr(getpass, "getpass", fallback)
    with pytest.raises(LMSError, match="терминал"):
        hidden_input("password")


def test_cancel_closes_client_preserves_session(store):
    clients = []

    def factory(store, timeout):
        client = SSOClient(store, timeout, transport=httpx.MockTransport(lambda _: response("password")))
        clients.append(client)
        return client

    def reader(_):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        interactive_login(store, reader=reader, write=lambda _: None, factory=factory)
    assert clients[0].client.is_closed
    assert store.get()[0]["value"] == "test-secret"
    with FileLock(store.root / "login.lock", timeout=0):
        pass


def test_concurrent_login_fails_before_network(store):
    with FileLock(store.root / "login.lock", timeout=0):
        with pytest.raises(LMSError, match="уже запущен"):
            interactive_login(store, factory=lambda *_: pytest.fail("must not connect"))


def test_interactive_attempt_limit_no_automatic_retries(store):
    requests = []

    def factory(store, timeout):
        def handle(request):
            requests.append(request)
            return response("password", error="Неверный пароль")

        return SSOClient(store, timeout, transport=httpx.MockTransport(handle))

    with pytest.raises(SSOError, match="предел попыток"):
        interactive_login(store, reader=lambda _: "wrong", write=lambda _: None, factory=factory)
    assert sum(r.method == "POST" for r in requests) == 5


def test_malformed_literal_does_not_leak_server_content():
    document = page("password").replace('"student@example.test"', r'"TOP-SECRET\q"')
    with pytest.raises(SSOError) as exc:
        parse_page(document)
    assert "TOP-SECRET" not in str(exc.value)


def test_sms_resend_matches_theme(store):
    posts = []

    def handle(request):
        if request.method == "POST":
            posts.append(parse_qs(request.content.decode()))
        return response("otp")

    client = SSOClient(store, transport=httpx.MockTransport(handle))
    try:
        client.start()
        client.submit("", resend=True)
    finally:
        client.close()
    assert posts == [{"action": ["sendCode"], "phoneNumber": ["79990000000"]}]


def test_interactive_success_keeps_secrets_out_of_output(store):
    answers = iter(["user@example.test", "TOP-SECRET", "not-a-code", "123456"])
    prompts, output, posts = [], [], []

    def factory(store, timeout):
        client = None

        def handle(request):
            if request.method == "POST":
                posts.append(request)
                if len(posts) == 1:
                    return response("password")
                if len(posts) == 2:
                    return response("otpEmail")
                return httpx.Response(302, headers={"location": CALLBACK + "?code=x&state=" + client.state})
            if request.url.host == "my.centraluniversity.ru":
                return httpx.Response(200, headers={"set-cookie": "session=fixture; Secure; Path=/"})
            return response("emailLogin")

        client = SSOClient(store, timeout, transport=httpx.MockTransport(handle), probe=lambda c: c)
        return client

    def read(prompt):
        prompts.append(prompt)
        return next(answers)

    result = interactive_login(store, reader=read, write=output.append, factory=factory)
    assert result["state"] == "authenticated"
    assert len(posts) == 3  # malformed OTP was not sent
    assert "TOP-SECRET" not in json.dumps([prompts, output, result])
    assert store.get()[0]["value"] == "fixture"
