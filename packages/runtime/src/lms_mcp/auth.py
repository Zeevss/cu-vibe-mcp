import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from .browser import open_driver, select_browser
from .config import PORTAL, AuthRequired, LMSError
from .session import SessionStore, cookie_jar, jar_cookies, normalize_cookies

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


@dataclass
class LoginFlow:
    id: str
    browser: str
    state: str = "opening"
    message: str = "Открываем окно браузера"
    stop: threading.Event = field(default_factory=threading.Event, repr=False)
    task: asyncio.Task | None = field(default=None, repr=False)

    def public(self):
        return dict(flow_id=self.id, browser=self.browser, state=self.state, message=self.message)


class AuthManager:
    def __init__(self, store: SessionStore, driver_factory=open_driver, probe=probe_sync):
        self.store = store
        self.driver_factory = driver_factory
        self.probe = probe
        self.flow: LoginFlow | None = None

    def busy(self):
        return self.flow is not None and self.flow.task is not None and not self.flow.task.done()

    async def begin(self, browser="auto", timeout_seconds=300):
        if not 30 <= timeout_seconds <= 900:
            raise LMSError("Время ожидания должно быть от 30 до 900 секунд")
        if self.busy():
            return self.flow.public()
        selected = select_browser(browser)
        flow = LoginFlow(uuid.uuid4().hex, selected.name)
        self.flow = flow
        flow.task = asyncio.create_task(asyncio.to_thread(self._capture, flow, selected, timeout_seconds))
        return flow.public()

    def _capture(self, flow, browser, timeout):
        driver = None
        try:
            driver = self.driver_factory(browser)
            driver.get(PORTAL + "/learn/")
            flow.state = "waiting_for_login"
            flow.message = "Войдите в открывшемся браузере. Сессия сохранится автоматически."
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and not flow.stop.is_set():
                if urlsplit(driver.current_url).hostname == urlsplit(PORTAL).hostname:
                    raw = driver.get_cookies()
                    if raw:
                        try:
                            cookies = self.probe(normalize_cookies(raw, "lms"))
                        except AuthRequired:
                            pass
                        else:
                            # Cancellation must not commit a session even if a probe was in flight.
                            if not flow.stop.is_set():
                                self.store.put(cookies)
                                flow.state = "authenticated"
                                flow.message = "Сессия LMS проверена и сохранена локально"
                                return
                flow.stop.wait(2)
            flow.state = "cancelled" if flow.stop.is_set() else "expired"
            flow.message = (
                "Вход отменён" if flow.stop.is_set() else "Время входа истекло; запустите его ещё раз"
            )
        except LMSError as exc:
            flow.state, flow.message = "failed", str(exc)
        except Exception:
            # Browser exceptions can contain URLs, cookies and form contents. Never return them.
            flow.state = "failed"
            flow.message = (
                "Не удалось открыть браузер или окно было закрыто. Проверьте наличие графической "
                "сессии и WebDriver; попробуйте другой браузер или импорт cookie."
            )
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    def status(self):
        return {
            "session": self.store.status(),
            "note_session": self.store.status("note"),
            "login": self.flow.public() if self.flow else None,
        }

    def cancel(self):
        if self.busy():
            self.flow.stop.set()
        return self.status()

    async def import_cookies(self, cookies, service="lms"):
        if self.busy():
            raise LMSError("Сначала завершите или отмените браузерный вход")
        if service == "lms":
            cookies = await asyncio.to_thread(self.probe, cookies)
        self.store.put(cookies, service)
        return {"service": service, "saved": True, "validated": service == "lms"}

    async def close(self):
        self.cancel()
        if self.flow and self.flow.task:
            # Wait for browser cleanup; quitting a driver with a bounded page-load timeout can take time.
            await self.flow.task
