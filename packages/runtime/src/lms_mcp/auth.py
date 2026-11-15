import asyncio

import httpx

from .config import PORTAL, AuthRequired, LMSError
from .session import SessionStore, cookie_jar, jar_cookies

PROBE = "/api/micro-lms/students/me"


def probe_sync(cookies: list[dict]) -> list[dict]:
    try:
        with httpx.Client(
            cookies=cookie_jar(cookies, "lms"), follow_redirects=False, timeout=15, trust_env=False
        ) as client:
            response = client.get(PORTAL + PROBE)
            if response.status_code in (301, 302, 303, 307, 308, 401, 403):
                raise AuthRequired("Сессия не принята порталом. Повторите вход или импорт cookie.")
            if response.status_code != 200 or "json" not in response.headers.get("content-type", ""):
                raise LMSError("Не удалось подтвердить сессию через API LMS")
            data = response.json()
            if not isinstance(data, dict) or "lateDaysBalance" not in data:
                raise LMSError("Неожиданная схема профиля LMS; сессия не сохранена")
            return jar_cookies(client.cookies, "lms")
    except httpx.HTTPError:
        raise LMSError("Портал недоступен при проверке сессии") from None
    except ValueError:
        raise LMSError("Профиль LMS вернул неверный JSON") from None


class AuthManager:
    """MCP never accepts credentials. Interactive SSO belongs to the local CLI."""

    def __init__(self, store: SessionStore, probe=probe_sync):
        self.store = store
        self.probe = probe

    async def begin(self):
        return {
            "state": "local_input_required",
            "command": "uv run --project packages/runtime --frozen cu-lms-mcp login",
            "message": (
                "Запустите команду в локальном терминале из папки репозитория. "
                "Она спросит email, пароль и код по шагам SSO. "
                "Не отправляйте секреты в чат. После завершения вызовите auth_status(validate=true)."
            ),
        }

    def status(self):
        return {
            "session": self.store.status(),
            "note_session": self.store.status("note"),
            "login": None,
            "login_method": "local_sso_cli",
        }

    def cancel(self):
        return {
            **self.status(),
            "message": "Локальный login отменяется через Ctrl+C в его терминале; MCP не управляет этим процессом.",
        }

    async def import_cookies(self, cookies, service="lms"):
        if service == "lms":
            cookies = await asyncio.to_thread(self.probe, cookies)
        self.store.put(cookies, service)
        return {"service": service, "saved": True, "validated": service == "lms"}

    async def close(self):
        pass
