from types import SimpleNamespace

import pytest

from lms_mcp.browser import Browser, binary_version, resolve_driver, select_browser, versions_match
from lms_mcp.config import LMSError


@pytest.fixture
def installed(monkeypatch):
    chrome = Browser("chrome", "/chrome", "chrome", "152.0.7977.64")
    chromium = Browser("chromium", "/chromium", "chrome", "153.0.8010.52")
    monkeypatch.delenv("SE_CHROMEDRIVER", raising=False)
    monkeypatch.setattr("lms_mcp.browser.detect_browsers", lambda: [chrome, chromium])
    monkeypatch.setattr("lms_mcp.browser.shutil.which", lambda _: "/system/chromedriver")
    monkeypatch.setattr("lms_mcp.browser.binary_version", lambda _: "153.0.8010.52")
    return chrome, chromium


def test_auto_chooses_compatible_chromium_instead_of_chrome(installed):
    assert select_browser().name == "chromium"
    assert select_browser("chrome").name == "chrome"


def test_matching_driver_does_not_use_manager(installed, monkeypatch):
    def unexpected(*args):
        pytest.fail("A matching local driver requires no network or manager")

    monkeypatch.setattr("selenium.webdriver.common.selenium_manager.SeleniumManager.binary_paths", unexpected)
    assert resolve_driver(installed[1]) == "/system/chromedriver"


def test_explicit_chrome_ignores_wrong_path_driver(installed, monkeypatch, tmp_path):
    resolved = tmp_path / "chromedriver-152"
    resolved.touch()
    captured = []

    def manager(self, args):
        captured.extend(args)
        return {"driver_path": str(resolved)}

    monkeypatch.setattr("selenium.webdriver.common.selenium_manager.SeleniumManager.binary_paths", manager)
    monkeypatch.setattr(
        "lms_mcp.browser.binary_version",
        lambda path: "152.0.7977.82" if path == str(resolved) else "153.0.8010.52",
    )
    assert resolve_driver(installed[0]) == str(resolved)
    assert "--skip-driver-in-path" in captured
    assert "--avoid-stats" in captured
    assert "--avoid-browser-download" in captured
    assert captured[captured.index("--browser-path") + 1] == "/chrome"
    assert captured[captured.index("--browser-version") + 1] == "152.0.7977.64"


def test_failed_download_has_actionable_error_without_raw_details(installed, monkeypatch):
    def fail(*args):
        raise RuntimeError("private URL and other raw details")

    monkeypatch.setattr("selenium.webdriver.common.selenium_manager.SeleniumManager.binary_paths", fail)
    with pytest.raises(LMSError) as error:
        resolve_driver(installed[0])
    assert "chrome 152.0.7977.64" in str(error.value)
    assert "--browser chromium" in str(error.value)
    assert "private URL" not in str(error.value)


def test_version_detection_is_bounded_and_parses_output(monkeypatch):
    def run(args, **kwargs):
        assert args == ["/browser", "--version"]
        assert kwargs["timeout"] == 3
        assert kwargs["check"] is False
        return SimpleNamespace(returncode=0, stdout="Google Chrome 152.0.7977.64\n")

    monkeypatch.setattr("lms_mcp.browser.subprocess.run", run)
    assert binary_version("/browser") == "152.0.7977.64"
    assert versions_match("152.0.7977.64", "152.0.7977.82")
    assert not versions_match("152.0.7977.64", "153.0.8010.52")
    assert not versions_match(None, "153.0.8010.52")


def test_manager_can_resolve_when_browser_version_is_unknown(monkeypatch, tmp_path):
    browser = Browser("chrome", "/chrome", "chrome")
    executable = tmp_path / "driver"
    executable.touch()
    monkeypatch.delenv("SE_CHROMEDRIVER", raising=False)
    monkeypatch.setattr("lms_mcp.browser.shutil.which", lambda _: None)
    monkeypatch.setattr("lms_mcp.browser.binary_version", lambda _: None)
    monkeypatch.setattr(
        "selenium.webdriver.common.selenium_manager.SeleniumManager.binary_paths",
        lambda *args: {"driver_path": str(executable)},
    )
    assert resolve_driver(browser) == str(executable)
