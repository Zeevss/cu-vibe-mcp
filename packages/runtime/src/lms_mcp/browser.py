"""Discover installed browsers; launch a fresh, temporary WebDriver profile."""

import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Config, LMSError


@dataclass(frozen=True)
class Browser:
    name: str
    path: str
    engine: str
    version: str | None = None

    def as_dict(self):
        return asdict(self)


# Ordered preference; the user can select any detected name explicitly.
CANDIDATES = [
    ("chrome", "chrome", ["google-chrome-stable", "google-chrome", "chrome"]),
    ("chromium", "chrome", ["chromium", "chromium-browser"]),
    ("edge", "edge", ["microsoft-edge-stable", "microsoft-edge", "msedge"]),
    ("brave", "chrome", ["brave-browser", "brave-browser-stable", "brave"]),
    ("firefox", "firefox", ["firefox", "firefox-esr"]),
    ("yandex", "chrome", ["yandex-browser-stable", "yandex-browser"]),
]
MAC = {
    "chrome": "Google Chrome.app/Contents/MacOS/Google Chrome",
    "chromium": "Chromium.app/Contents/MacOS/Chromium",
    "edge": "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "brave": "Brave Browser.app/Contents/MacOS/Brave Browser",
    "firefox": "Firefox.app/Contents/MacOS/firefox",
    "yandex": "Yandex.app/Contents/MacOS/Yandex",
}
WIN = {
    "chrome": ["Google/Chrome/Application/chrome.exe"],
    "chromium": ["Chromium/Application/chrome.exe"],
    "edge": ["Microsoft/Edge/Application/msedge.exe"],
    "brave": ["BraveSoftware/Brave-Browser/Application/brave.exe"],
    "firefox": ["Mozilla Firefox/firefox.exe"],
    "yandex": ["Yandex/YandexBrowser/Application/browser.exe"],
}


def binary_version(path: str) -> str | None:
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=3, check=False)
        match = re.search(r"\b(\d+\.\d+\.\d+(?:\.\d+)?)\b", result.stdout[:4096])
        return match.group(1) if result.returncode == 0 and match else None
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def versions_match(browser_version: str | None, driver_version: str | None) -> bool:
    return bool(
        browser_version and driver_version and browser_version.split(".")[:3] == driver_version.split(".")[:3]
    )


def local_driver(browser: Browser) -> str | None:
    names = {
        "chrome": ("SE_CHROMEDRIVER", "chromedriver"),
        "edge": ("SE_EDGEDRIVER", "msedgedriver"),
        "firefox": ("SE_GECKODRIVER", "geckodriver"),
    }
    variable, command = names[browser.engine]
    return os.environ.get(variable) or shutil.which(command)


def compatible_local_driver(browser: Browser) -> str | None:
    executable = local_driver(browser)
    if executable and (
        browser.engine == "firefox"
        or versions_match(browser.version or binary_version(browser.path), binary_version(executable))
    ):
        return executable
    return None


def resolve_driver(browser: Browser) -> str:
    from selenium.webdriver.common.selenium_manager import SeleniumManager

    if executable := compatible_local_driver(browser):
        return executable
    overrides = {"chrome": "SE_CHROMEDRIVER", "edge": "SE_EDGEDRIVER", "firefox": "SE_GECKODRIVER"}
    if os.environ.get(overrides[browser.engine]):
        raise LMSError(
            f"Драйвер из {overrides[browser.engine]} не совместим с выбранным браузером. "
            "Исправьте эту переменную или выберите browser=chromium в get_syllabus."
        )
    version = browser.version or binary_version(browser.path)
    args = [
        "--browser",
        browser.engine,
        "--browser-path",
        browser.path,
        "--skip-driver-in-path",
        "--avoid-browser-download",
        "--avoid-stats",
        "--timeout",
        "30",
        "--cache-path",
        os.environ.get("SE_CACHE_PATH", str(Config.from_env().data_dir / "selenium")),
    ]
    if version:
        args += ["--browser-version", version]
    try:
        result = SeleniumManager().binary_paths(args)
        executable = result.get("driver_path")
        if not executable or not Path(executable).is_file():
            raise ValueError()
        if (
            browser.engine != "firefox"
            and version
            and not versions_match(version, binary_version(executable))
        ):
            raise ValueError()
        return executable
    except Exception:
        raise LMSError(
            f"Не удалось получить совместимый драйвер для {browser.name} {version or ''}. "
            "Проверьте доступ к загрузкам драйверов; выберите browser=chromium в get_syllabus "
            "или настройте совместимый WebDriver. Драйвер в PATH менять или удалять не требуется."
        ) from None


def detect_browsers() -> list[Browser]:
    result = []
    for name, engine, commands in CANDIDATES:
        paths = [p for cmd in commands if (p := shutil.which(cmd))]
        if sys.platform == "darwin":
            paths += [str(root / MAC[name]) for root in (Path("/Applications"), Path.home() / "Applications")]
        if os.name == "nt":
            paths += [
                str(Path(root) / sub)
                for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
                if (root := os.environ.get(env))
                for sub in WIN[name]
            ]
        found = next((p for p in paths if Path(p).is_file() and os.access(p, os.X_OK)), None)
        if found:
            result.append(Browser(name, found, engine, binary_version(found)))
    return result


def select_browser(name: str = "auto") -> Browser:
    browsers = detect_browsers()
    if name == "auto" and browsers:
        # Prefer a browser with a verified local driver over one that requires a download.
        return next((b for b in browsers if compatible_local_driver(b)), browsers[0])
    match = next((b for b in browsers if b.name == name), None)
    if match:
        return match
    raise LMSError(
        "Браузер не найден. Установите Chrome/Chromium/Edge/Brave/Firefox "
        "или используйте импорт cookie. Список: cu-lms-mcp browsers"
    )


def open_driver(browser: Browser, headless=False):
    if (
        not headless
        and sys.platform.startswith("linux")
        and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    ):
        raise LMSError(
            "Для входа через браузер нужна графическая сессия. Используйте import-cookie или запустите MCP на рабочем столе."
        )
    # WebDriver is a local control channel. Preserve the user's other proxy exclusions.
    for key, other in [("NO_PROXY", "no_proxy"), ("no_proxy", "NO_PROXY")]:
        hosts = [
            host.strip() for host in os.environ.get(key, os.environ.get(other, "")).split(",") if host.strip()
        ]
        for host in ("localhost", "127.0.0.1", "::1"):
            if host not in hosts:
                hosts.append(host)
        os.environ[key] = ",".join(hosts)

    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.webdriver.firefox.service import Service as FirefoxService

    class IPv4Loopback:
        @property
        def service_url(self):
            # Some hosts resolve localhost to an unreachable IPv6 loopback first.
            # The driver is local; avoid DNS/proxy routing and long connect timeouts.
            return f"http://127.0.0.1:{self.port}"

    class LocalChromeService(IPv4Loopback, ChromeService):
        pass

    class LocalEdgeService(IPv4Loopback, EdgeService):
        pass

    class LocalFirefoxService(IPv4Loopback, FirefoxService):
        pass

    executable = resolve_driver(browser)
    if browser.engine == "firefox":
        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument("-headless")
        options.binary_location = browser.path
        service = LocalFirefoxService(executable_path=executable)
        driver = webdriver.Firefox(options=options, service=service)
    else:
        options = webdriver.EdgeOptions() if browser.engine == "edge" else webdriver.ChromeOptions()
        options.binary_location = browser.path
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-dev-shm-usage")
        # Never attach to the user's default profile or enable remote debugging on an existing browser.
        if browser.engine == "edge":
            service = LocalEdgeService(executable_path=executable)
            driver = webdriver.Edge(options=options, service=service)
        else:
            service = LocalChromeService(executable_path=executable)
            driver = webdriver.Chrome(options=options, service=service)
    driver.set_page_load_timeout(40)
    driver.set_script_timeout(15)
    return driver
