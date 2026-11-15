"""CU's Keycloak theme over HTTPS. No JavaScript execution or browser profiles.

The theme posts ordinary forms, but describes them in window.authConfiguration.
Only known scalar literals are read; remote JavaScript is never evaluated.
"""

import ast
import getpass
import html
import json
import re
import secrets
import sys
import time
import warnings
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from filelock import FileLock, Timeout

from .auth import probe_sync
from .config import PORTAL, LMSError
from .session import jar_cookies

IDP = "https://id.centraluniversity.ru"
REALM = "/realms/central-university/"
AUTHORIZE = IDP + REALM + "protocol/openid-connect/auth"
CALLBACK = PORTAL + "/api/account/signin/callback"
LITERAL = r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|true|false|null|\d+)"""


class SSOError(LMSError):
    def __init__(self, state, message):
        super().__init__(message)
        self.state = state


def literal(value):
    if value.startswith("'"):
        return ast.literal_eval(value)
    return json.loads(value)


def scalar(script, section, key, default=""):
    """Read a known object property and any later literal assignment override."""
    value = default
    block = re.search(r"\b" + re.escape(section) + r"\s*:\s*\{", script)
    if block:
        # Balance objects while skipping quoted strings; nested systemMessage is common.
        depth, end = 1, block.end()
        for token in re.finditer(r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{}]""", script[end:]):
            if token[0] == "{":
                depth += 1
            elif token[0] == "}":
                depth -= 1
            if depth == 0:
                end += token.start()
                break
        match = re.search(
            r"\b" + re.escape(key) + r"\s*:\s*(" + LITERAL + r")\s*[,}]?", script[block.end() : end]
        )
        if match:
            value = literal(match[1])
    assignment = r"window\.authConfiguration\." + re.escape(section + "." + key)
    for match in re.finditer(assignment + r"\s*=\s*(" + LITERAL + r")\s*;", script):
        value = literal(match[1])
    return value


@dataclass(repr=False)
class Page:
    kind: str
    action: str = field(repr=False)
    username: str = field(default="", repr=False)
    credential: str = field(default="", repr=False)
    phone: str = field(default="", repr=False)
    error: bool = False


def parse_page(document):
    try:
        return _parse_page(document)
    except (ValueError, SyntaxError, TypeError, RecursionError):
        raise SSOError("invalid_response", "Не удалось разобрать форму SSO; вход остановлен.") from None


def _parse_page(document):
    soup = BeautifulSoup(document, "html.parser")
    script = "\n".join(s.get_text() for s in soup.find_all("script") if not s.get("src"))
    kind = scalar(script, "currentState", "activePage")
    if scalar(script, "currentState", "recaptchaEnabled", False):
        raise SSOError(
            "captcha_required", "SSO требует CAPTCHA. Завершите вход на сайте и импортируйте cookie локально."
        )
    blocked = {
        "updatePassword": "SSO требует установить или сменить пароль. Сделайте это на сайте ЦУ и повторите login.",
        "resetPassword": "Нужно восстановление пароля на сайте ЦУ, затем повторный login.",
        "recoveryLinkSent": "SSO отправил ссылку восстановления. Откройте её самостоятельно, затем повторите login.",
        "verifyEmail": "Подтвердите почту по ссылке от ЦУ, затем повторите login.",
        "otpConfigure": "SSO требует настройки телефона/MFA на сайте ЦУ, затем повторного login.",
        "registration": "SSO требует регистрации. Завершите её на сайте ЦУ.",
    }
    if kind in blocked:
        raise SSOError(kind, blocked[kind])
    message = str(scalar(script, "systemMessage", "content"))
    lower = message.lower()
    if any(
        x in lower for x in ("temporarily", "locked", "disabled", "заблокир", "too many", "слишком много")
    ):
        raise SSOError(
            "account_unavailable",
            "SSO ограничил вход или заблокировал аккаунт. Повторите позже либо обратитесь в поддержку ЦУ.",
        )
    if any(x in lower for x in ("expired", "истек", "истёк")) and kind not in ("otp", "otpEmail"):
        raise SSOError("expired", "Срок входа истёк. Запустите login заново.")
    if kind not in ("emailLogin", "passwordLogin", "password", "otp", "otpEmail"):
        raise SSOError(
            "unsupported_step",
            "Неизвестный шаг SSO: вход остановлен. Используйте локальный импорт cookie и сообщите об изменении формы.",
        )
    action = html.unescape(str(scalar(script, "urls", "loginAction")))
    url = urlsplit(action)
    if (url.scheme, url.netloc, url.path) != (
        "https",
        "id.centraluniversity.ru",
        REALM + "login-actions/authenticate",
    ) or url.fragment:
        raise SSOError("unsupported_step", "SSO вернул неизвестный адрес формы; данные не отправлены.")
    return Page(
        kind,
        action,
        str(scalar(script, "currentState", "userName")),
        str(scalar(script, "currentState", "selectedCredential")),
        str(scalar(script, "currentState", "phoneNumber")),
        scalar(script, "systemMessage", "level") == "error"
        or bool(scalar(script, "messages", "userName"))
        or message in ("noOngoingVerificationProcess", "phoneTokenCodeDoesNotMatch"),
    )


class SSOClient:
    def __init__(self, store, timeout=300, *, transport=None, probe=probe_sync):
        if not 30 <= timeout <= 900:
            raise LMSError("Время ожидания должно быть от 30 до 900 секунд")
        self.store, self.probe = store, probe
        self.deadline = time.monotonic() + timeout
        self.state = secrets.token_urlsafe(32)
        self.page = None
        self.callback_seen = False
        self.client = httpx.Client(transport=transport, trust_env=False, follow_redirects=False, timeout=20)

    def close(self):
        self.page = None
        self.client.cookies.clear()
        self.client.close()

    def _check_url(self, url):
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise SSOError("unsafe_redirect", "SSO вернул некорректный адрес; вход остановлен.") from None
        if (
            parsed.scheme != "https"
            or parsed.netloc not in ("id.centraluniversity.ru", "my.centraluniversity.ru")
            or parsed.fragment
        ):
            raise SSOError("unsafe_redirect", "SSO перенаправил на неизвестный адрес; вход остановлен.")
        if parsed.netloc == "my.centraluniversity.ru" and not self.callback_seen:
            query = parse_qs(parsed.query)
            if (
                parsed.path != "/api/account/signin/callback"
                or query.get("state") != [self.state]
                or len(query.get("code", [])) != 1
            ):
                raise SSOError("invalid_callback", "Не удалось проверить ответ SSO; запустите login заново.")
            self.callback_seen = True

    def _request(self, method, url, data=None):
        for _ in range(12):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise SSOError("expired", "Срок входа истёк. Запустите login заново.")
            self._check_url(url)
            try:
                with self.client.stream(method, url, data=data, timeout=min(20, remaining)) as response:
                    if response.status_code == 429:
                        raise SSOError(
                            "rate_limited", "SSO ограничил частоту запросов. Повторите вход позже."
                        )
                    if response.status_code in (301, 302, 303, 307, 308):
                        if method == "POST" and response.status_code in (307, 308):
                            raise SSOError(
                                "unsafe_redirect", "SSO запросил повторную пересылку формы; вход остановлен."
                            )
                        location = response.headers.get("location")
                        if not location:
                            raise SSOError("invalid_response", "SSO вернул перенаправление без адреса.")
                        url, method, data = urljoin(url, location), "GET", None
                        continue
                    if response.status_code >= 400:
                        raise SSOError(
                            "unavailable", "SSO отклонил запрос или недоступен. Повторите login позже."
                        )
                    body = bytearray()
                    for part in response.iter_bytes():
                        if time.monotonic() >= self.deadline:
                            raise SSOError("expired", "Срок входа истёк. Запустите login заново.")
                        body.extend(part)
                        if len(body) > 1024 * 1024:
                            raise SSOError("invalid_response", "Ответ SSO превышает допустимый размер.")
                    if self.callback_seen and urlsplit(url).netloc == "my.centraluniversity.ru":
                        cookies = self.probe(jar_cookies(self.client.cookies, "lms"))
                        if time.monotonic() >= self.deadline:
                            raise SSOError("expired", "Срок входа истёк; сессия не сохранена.")
                        self.store.put(cookies)
                        self.page = None
                        return "authenticated"
                    self.page = parse_page(body.decode("utf-8", errors="replace"))
                    return self.page.kind
            except httpx.HTTPError:
                # Exceptions can contain action URLs, one-time codes and form data.
                raise SSOError(
                    "network_error",
                    "Нет связи с SSO. Результат отправки может быть неизвестен; запустите login заново.",
                ) from None
            except (ValueError, httpx.InvalidURL):
                raise SSOError(
                    "invalid_response", "SSO вернул некорректный ответ; вход остановлен."
                ) from None
        raise SSOError("redirect_loop", "Слишком много перенаправлений SSO; вход остановлен.")

    def start(self):
        url = str(
            httpx.URL(
                AUTHORIZE,
                params={
                    "response_type": "code",
                    "client_id": "api-gateway",
                    "scope": "openid email offline_access",
                    "redirect_uri": CALLBACK,
                    "state": self.state,
                },
            )
        )
        return self._request("GET", url)

    def submit(self, value, *, username="", resend=False):
        page = self.page
        if not page:
            raise LMSError("Сначала начните вход")
        if resend and page.kind not in ("otp", "otpEmail"):
            raise LMSError("Повторная отправка доступна только на шаге кода")
        if page.kind == "emailLogin":
            data = {"username": value}
        elif page.kind == "password":
            data = {"password": value}
        elif page.kind == "passwordLogin":
            data = {"username": username, "password": value, "credentialId": page.credential}
        elif page.kind == "otpEmail":
            action = "resend" if resend else "submit"
            data = {"otp": "" if resend else value, action: action}
        else:
            if not page.phone:
                raise SSOError(
                    "unsupported_step", "SSO не указал телефон для SMS. Завершите настройку MFA на сайте ЦУ."
                )
            data = {"action": "sendCode" if resend else "verify", "phoneNumber": page.phone}
            if not resend:
                data.update(code=value, credentialId=page.credential)
        # Consume the form even on a network error. Never retry a POST automatically.
        self.page = None
        return self._request("POST", page.action, data)


def hidden_input(prompt):
    # getpass normally falls back to echoing stdin; fail instead, including in cloud chats.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except (getpass.GetPassWarning, EOFError):
            raise LMSError(
                "Нужен локальный интерактивный терминал со скрытым вводом. Запустите login самостоятельно."
            ) from None


def interactive_login(store, timeout=300, *, reader=hidden_input, write=None, factory=SSOClient):
    write = write or (lambda text: print(text, file=sys.stderr))
    store.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = FileLock(str(store.root / "login.lock"), mode=0o600)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise LMSError("Другой login уже запущен. Завершите его или отмените через Ctrl+C.") from None
    client = None
    try:
        client = factory(store, timeout)
        kind = client.start()
        attempts = {}
        resends = 0
        write("Вход в SSO ЦУ. Ввод скрыт. Ctrl+C — отмена. Пароль и коды не сохраняются.")
        while kind != "authenticated":
            if client.page.error:
                write("SSO не принял данные или код истёк. Проверьте ввод; автоматического повтора нет.")
            attempts[kind] = attempts.get(kind, 0) + 1
            if attempts[kind] > 5:
                raise SSOError(
                    "attempt_limit",
                    "Достигнут предел попыток этого шага. Повторите login позже или восстановите доступ на сайте ЦУ.",
                )
            username = ""
            if kind in ("emailLogin", "passwordLogin"):
                username = reader("Email ЦУ: ").strip()
                if not username:
                    write("Email не может быть пустым.")
                    continue
            if kind == "emailLogin":
                value = username
            elif kind in ("password", "passwordLogin"):
                value = reader("Пароль: ")
            else:
                value = reader("Код подтверждения (или /resend для нового кода): ").strip()
            resend = value == "/resend" and kind in ("otp", "otpEmail")
            if not value:
                write("Пустое значение не отправлено.")
                continue
            if resend:
                resends += 1
                if resends > 2:
                    raise SSOError(
                        "attempt_limit", "Достигнут предел повторной отправки кода. Повторите login позже."
                    )
            elif kind in ("otp", "otpEmail") and not re.fullmatch(r"[0-9]{6}", value):
                write("Ожидается шестизначный код.")
                continue
            kind = client.submit(value, username=username, resend=resend)
            value = username = ""
        return {"state": "authenticated", "message": "Сессия LMS проверена и сохранена локально"}
    finally:
        if client:
            client.close()
        lock.release()
