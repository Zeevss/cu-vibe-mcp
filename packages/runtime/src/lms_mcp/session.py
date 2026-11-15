"""Only explicitly supplied cookies or cookies from our own SSO flow are used."""

import json
import math
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from filelock import FileLock

from .config import ORIGINS, LMSError

TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9a-zA-Z-]+$")


def service_host(service: str) -> str:
    if service not in ORIGINS:
        raise LMSError("service должен быть lms или note")
    return urlsplit(ORIGINS[service]).hostname


def normalize_cookies(raw: list, service: str, allow_empty=False) -> list[dict]:
    host = service_host(service)
    result = []
    for c in raw:
        if not isinstance(c, dict):
            raise LMSError("Неверный объект cookie")
        name, value = c.get("name"), c.get("value")
        if not isinstance(name, str) or not TOKEN.fullmatch(name):
            raise LMSError("Неверное имя cookie")
        if not isinstance(value, str) or any(ord(x) < 0x21 or ord(x) > 0x7E or x == ";" for x in value):
            raise LMSError("Неверное значение cookie")
        domain = c.get("domain") or host
        if not isinstance(domain, str):
            raise LMSError("Неверный домен cookie")
        domain = domain.lower()
        bare = domain.lstrip(".")
        # Accept parent domain cookies only for the service for which they were supplied.
        if not (host == bare or (domain.startswith(".") and host.endswith("." + bare))):
            continue
        if bare not in {host, "centraluniversity.ru", "cu.ru"}:
            continue
        path = c.get("path", "/")
        if not isinstance(path, str) or not path.startswith("/") or any(ord(x) < 32 for x in path):
            raise LMSError("Неверный путь cookie")
        expires = c.get("expires", c.get("expiry", -1))
        try:
            expires = float(expires)
        except (TypeError, ValueError):
            raise LMSError("Неверный срок cookie") from None
        if not math.isfinite(expires):
            raise LMSError("Неверный срок cookie")
        if expires > 0 and expires <= time.time():
            continue
        result.append(
            dict(
                name=name,
                value=value,
                domain=domain,
                path=path,
                expires=expires,
                secure=bool(c.get("secure", True)),
            )
        )
    if not result and not allow_empty:
        raise LMSError("Нет действующих cookies для выбранного сервиса")
    return result


def parse_cookies(text: str, service: str = "lms") -> list[dict]:
    text = text.strip()
    if not text:
        raise LMSError("Пустая cookie")
    if text.startswith(("[", "{")):
        try:
            data = json.loads(text)
        except ValueError:
            raise LMSError("Некорректный JSON cookies") from None
        if isinstance(data, dict):
            data = data.get("cookies")
        if not isinstance(data, list):
            raise LMSError("Ожидается массив cookies или объект с полем cookies")
        return normalize_cookies(data, service)
    if "\t" in text:
        cookies = []
        for line in text.splitlines():
            line = line.removeprefix("#HttpOnly_")
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) != 7:
                raise LMSError("Неверный Netscape cookie-файл")
            domain, _, path, secure, expires, name, value = fields
            cookies.append(
                dict(
                    domain=domain,
                    path=path,
                    secure=secure.upper() == "TRUE",
                    expires=expires,
                    name=name,
                    value=value,
                )
            )
        return normalize_cookies(cookies, service)
    if "\n" in text or "\r" in text:
        raise LMSError("Ожидается одна строка Cookie, JSON или Netscape-файл")
    text = re.sub(r"^cookie:\s*", "", text, flags=re.I)
    cookies = []
    for part in text.split(";"):
        name, separator, value = part.strip().partition("=")
        if not separator:
            raise LMSError("Ожидается Cookie: name=value; name2=value2")
        cookies.append(dict(name=name, value=value))
    return normalize_cookies(cookies, service)


def cookie_jar(cookies: list[dict], service: str) -> httpx.Cookies:
    """Host-scope every cookie: LMS credentials must never travel to Note or S3."""
    jar = httpx.Cookies()
    host = service_host(service)
    for c in cookies:
        if c["expires"] > 0 and c["expires"] <= time.time():
            continue
        jar.set(c["name"], c["value"], domain=host, path=c["path"])
    return jar


def jar_cookies(jar: httpx.Cookies, service: str) -> list[dict]:
    return normalize_cookies(
        [
            dict(
                name=c.name,
                value=c.value,
                domain=c.domain,
                path=c.path,
                expires=c.expires or -1,
                secure=c.secure,
            )
            for c in jar.jar
        ],
        service,
        allow_empty=True,
    )


class SessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "session.json"
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "services": {}}
        try:
            data = json.loads(self.path.read_text())
            if (
                not isinstance(data, dict)
                or data.get("version") != 1
                or not isinstance(data.get("services"), dict)
            ):
                raise ValueError()
            for service, value in data["services"].items():
                if (
                    service not in ORIGINS
                    or not isinstance(value, dict)
                    or not isinstance(value.get("cookies"), list)
                ):
                    raise ValueError()
            return data
        except (ValueError, OSError):
            raise LMSError("Повреждён session.json; выполните logout, затем повторите вход") from None

    def get(self, service="lms") -> list[dict]:
        service_host(service)
        with self.lock:
            value = self._read()["services"].get(service, {}).get("cookies", [])
            return normalize_cookies(value, service, allow_empty=True) if value else []

    def _process_lock(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.root.chmod(0o700)
        return FileLock(self.root / ".session.lock", timeout=10, mode=0o600)

    def _write(self, data):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.root.chmod(0o700)
        fd, name = tempfile.mkstemp(dir=self.root, prefix=".session-")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def put(self, cookies, service="lms"):
        cookies = normalize_cookies(cookies, service)
        with self.lock, self._process_lock():
            data = self._read()
            data["services"][service] = {"cookies": cookies, "saved_at": time.time()}
            self._write(data)

    def rotate(self, previous, cookies, service="lms"):
        with self.lock, self._process_lock():
            data = self._read()
            current = data["services"].get(service, {}).get("cookies", [])
            if current != previous:
                return
            if cookies:
                data["services"][service] = {
                    "cookies": normalize_cookies(cookies, service),
                    "saved_at": time.time(),
                }
            else:
                data["services"].pop(service, None)
            self._write(data)

    def clear(self, service="lms"):
        service_host(service)
        with self.lock, self._process_lock():
            try:
                data = self._read()
            except LMSError:
                data = {"version": 1, "services": {}}
            data["services"].pop(service, None)
            self._write(data)

    def status(self, service="lms"):
        try:
            cookies = self.get(service)
            return {"service": service, "has_session": bool(cookies), "cookie_count": len(cookies)}
        except LMSError:
            return {
                "service": service,
                "has_session": False,
                "cookie_count": 0,
                "message": "Сессия отсутствует, повреждена или истекла",
            }
