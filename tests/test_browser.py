import pytest
import socket
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

from app.applications.browser import BrowserReader, BrowserTabSession
from app.security.registry import ToolRegistry
from app.security.policy import RiskLevel
from database.database import Database
from app.applications.browser import register_safe_browser_tools


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///C:/Windows/win.ini",
        "http://localhost:11434/api/tags",
        "http://127.0.0.1/",
        "http://192.168.1.1/",
        "https://user:password@example.com/",
    ],
)
def test_browser_blocks_non_web_and_local_urls(url):
    with pytest.raises((ValueError, PermissionError)):
        BrowserReader.validate_url(url)


def test_browser_accepts_public_http_and_https_urls():
    assert BrowserReader.validate_url("https://example.com/path") == "https://example.com/path"
    assert BrowserReader.validate_url("http://example.org") == "http://example.org"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.4.3.2", "169.254.1.1", "::1"])
def test_browser_blocks_public_names_resolving_to_local_addresses(monkeypatch, address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(
        "app.applications.browser.socket.getaddrinfo",
        lambda host, port, type: [(family, type, 6, "", (address, port))],
    )

    with pytest.raises(PermissionError, match="resolves to a private or reserved"):
        BrowserReader.validate_resolved_url("https://looks-public.example/path")


def test_public_page_reader_is_available_as_a_validated_read_only_tool(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    reader = Mock()
    reader.read_page.return_value = {"url": "https://example.com", "trust": "untrusted_external_content"}
    registry = ToolRegistry(database)
    register_safe_browser_tools(registry, reader)

    result = registry.execute("read_public_webpage", {"url": "https://example.com"})

    assert result.value["trust"] == "untrusted_external_content"
    assert result.verified
    assert registry.list_tools()[0].risk is RiskLevel.READ_ONLY
    assert registry.list_tools()[0].retry_limit == 2
    with pytest.raises((ValueError, PermissionError)):
        registry.execute("read_public_webpage", {"url": "http://127.0.0.1/"})


def _install_fake_playwright(monkeypatch, locator):
    class Context:
        def __init__(self):
            self.options = None
            self.request_guard = None
            self.closed = False

        def route(self, _pattern, handler):
            self.request_guard = handler

        def new_page(self):
            return page

        def close(self):
            self.closed = True

    class Browser:
        def __init__(self):
            self.context = Context()
            self.closed = False

        def new_context(self, **options):
            self.context.options = options
            return self.context

        def close(self):
            self.closed = True

    class Page:
        url = "https://example.com/form"

        def set_default_timeout(self, _timeout):
            pass

        def on(self, *_args):
            pass

        def goto(self, target, **_kwargs):
            self.url = target

        def get_by_label(self, _label, *, exact):
            assert exact is True
            return locator

    page = Page()
    browser = Browser()
    chromium = SimpleNamespace(launch=Mock(return_value=browser))

    class PlaywrightContext:
        def __enter__(self):
            return SimpleNamespace(chromium=chromium)

        def __exit__(self, *_args):
            return False

    package = ModuleType("playwright")
    package.__path__ = []
    sync_api = ModuleType("playwright.sync_api")
    sync_api.sync_playwright = PlaywrightContext
    sync_api.TimeoutError = type("TimeoutError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setattr(
        BrowserReader,
        "validate_resolved_url",
        classmethod(lambda cls, url: cls.validate_url(url)),
    )
    return browser, page, chromium


def _install_fake_browser_session(monkeypatch, *, response_status=None):
    class Locator:
        def __init__(self, page):
            self.page = page

        def inner_text(self, **_kwargs):
            return "Public text at " + self.page.url

    class Page:
        def __init__(self):
            self.url = "about:blank"
            self.closed = False

        def set_default_timeout(self, _timeout):
            pass

        def on(self, *_args):
            pass

        def goto(self, target, **_kwargs):
            self.url = target
            if response_status is not None:
                return SimpleNamespace(status=response_status)
            return None

        def title(self):
            return "Title for " + self.url

        def locator(self, _selector):
            return Locator(self)

        def close(self):
            self.closed = True

    class Context:
        def __init__(self):
            self.options = None
            self.request_guard = None
            self.pages = []
            self.closed = False

        def route(self, _pattern, handler):
            self.request_guard = handler

        def new_page(self):
            page = Page()
            self.pages.append(page)
            return page

        def close(self):
            self.closed = True

    class Browser:
        def __init__(self):
            self.context = Context()
            self.closed = False

        def new_context(self, **options):
            self.context.options = options
            return self.context

        def close(self):
            self.closed = True

    browser = Browser()
    chromium = SimpleNamespace(launch=Mock(return_value=browser))
    playwright = SimpleNamespace(chromium=chromium)

    class Manager:
        def __init__(self):
            self.exited = False

        def __enter__(self):
            return playwright

        def __exit__(self, *_args):
            self.exited = True
            return False

    managers = []

    def sync_playwright():
        manager = Manager()
        managers.append(manager)
        return manager

    package = ModuleType("playwright")
    package.__path__ = []
    sync_api = ModuleType("playwright.sync_api")
    sync_api.sync_playwright = sync_playwright
    sync_api.TimeoutError = type("TimeoutError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setattr(
        BrowserReader,
        "validate_resolved_url",
        classmethod(lambda cls, url: cls.validate_url(url)),
    )
    return browser, chromium, managers


def test_public_page_reader_is_stateless_javascript_disabled_and_read_only(monkeypatch):
    browser, chromium, managers = _install_fake_browser_session(monkeypatch)

    result = BrowserReader().read_page("https://example.com")

    assert result["trust"] == "untrusted_external_content"
    assert browser.context.options == {
        "accept_downloads": False,
        "java_script_enabled": False,
    }
    assert browser.context.closed and browser.closed and managers[0].exited
    chromium.launch.assert_called_once_with(headless=True)

    class Route:
        aborted = False
        continued = False

        def abort(self):
            self.aborted = True

        def continue_(self):
            self.continued = True

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        route = Route()
        browser.context.request_guard(
            route,
            SimpleNamespace(method=method, url="https://example.com/action"),
        )
        assert route.aborted and not route.continued

    for method in ("GET", "HEAD"):
        route = Route()
        browser.context.request_guard(
            route,
            SimpleNamespace(method=method, url="https://example.com/page"),
        )
        assert route.continued and not route.aborted


@pytest.mark.parametrize("status", [408, 425, 429, 500, 503, 599])
def test_public_page_reader_preserves_retryable_http_status(monkeypatch, status):
    _install_fake_browser_session(monkeypatch, response_status=status)

    with pytest.raises(RuntimeError) as raised:
        BrowserReader().read_page("https://example.com")

    assert getattr(raised.value, "status_code", None) == status


class _FakeFormLocator:
    def __init__(self, *, value="", tag="input", input_type="text", readonly=False,
                 visible=True, enabled=True, editable=True, count=1):
        self.value = value
        self.metadata = {"tag": tag, "type": input_type, "readOnly": readonly}
        self.visible = visible
        self.enabled = enabled
        self.editable = editable
        self.matches = count
        self.fill_called = False

    def count(self):
        return self.matches

    def is_visible(self):
        return self.visible

    def is_enabled(self):
        return self.enabled

    def is_editable(self):
        return self.editable

    def evaluate(self, _expression):
        return self.metadata

    def input_value(self):
        return self.value

    def fill(self, value, **_kwargs):
        self.fill_called = True
        self.value = value


def test_public_form_fill_uses_stateless_script_disabled_context_and_never_submits(monkeypatch):
    locator = _FakeFormLocator()
    browser, _page, chromium = _install_fake_playwright(monkeypatch, locator)
    result = BrowserReader().fill_empty_public_form_field(
        "https://example.com/form",
        "Contact email",
        "person@example.com",
    )

    assert locator.fill_called
    assert browser.context.options == {"accept_downloads": False, "java_script_enabled": False}
    assert result["filled"] is True
    assert result["submitted"] is False
    assert result["text_length"] == len("person@example.com")
    assert result["text_sha256"]
    assert "text" not in result
    assert browser.context.closed and browser.closed
    chromium.launch.assert_called_once_with(headless=True)

    class Route:
        aborted = False
        continued = False

        def abort(self):
            self.aborted = True

        def continue_(self):
            self.continued = True

    post_route = Route()
    browser.context.request_guard(post_route, SimpleNamespace(method="POST", url="https://example.com/send"))
    assert post_route.aborted and not post_route.continued
    get_route = Route()
    browser.context.request_guard(get_route, SimpleNamespace(method="GET", url="https://example.com/form"))
    assert get_route.continued and not get_route.aborted


@pytest.mark.parametrize(
    "locator",
    [
        _FakeFormLocator(input_type="password"),
        _FakeFormLocator(input_type="hidden"),
        _FakeFormLocator(input_type="submit"),
        _FakeFormLocator(tag="select"),
        _FakeFormLocator(readonly=True),
        _FakeFormLocator(value="already entered"),
        _FakeFormLocator(visible=False),
        _FakeFormLocator(enabled=False),
        _FakeFormLocator(editable=False),
        _FakeFormLocator(count=2),
    ],
)
def test_public_form_fill_refuses_protected_ambiguous_or_nonempty_controls(monkeypatch, locator):
    _install_fake_playwright(monkeypatch, locator)
    with pytest.raises((PermissionError, ValueError)):
        BrowserReader().fill_empty_public_form_field(
            "https://example.com/form", "Contact", "value"
        )
    assert locator.fill_called is False


def test_browser_channel_allowlist_supports_chromium_chrome_edge_and_brave():
    assert BrowserReader.validate_channel("chromium") == "chromium"
    assert BrowserReader.validate_channel("chrome") == "chrome"
    assert BrowserReader.validate_channel("msedge") == "msedge"
    assert BrowserReader.validate_channel("brave") == "brave"
    with pytest.raises(ValueError, match="Browser channel"):
        BrowserReader.validate_channel("firefox")


def test_brave_browser_launch_uses_discovered_custom_executable(monkeypatch, tmp_path):
    brave = tmp_path / "brave.exe"
    brave.touch()
    monkeypatch.setattr(BrowserReader, "find_brave_executable", staticmethod(lambda: brave))
    chromium = SimpleNamespace(launch=Mock(return_value="browser"))

    result = BrowserReader._launch_browser(SimpleNamespace(chromium=chromium), "brave")

    assert result == "browser"
    chromium.launch.assert_called_once_with(headless=True, executable_path=str(brave))


def test_brave_browser_launch_reports_missing_install(monkeypatch):
    monkeypatch.setattr(BrowserReader, "find_brave_executable", staticmethod(lambda: None))

    with pytest.raises(FileNotFoundError, match="Brave is not installed"):
        BrowserReader._launch_browser(SimpleNamespace(chromium=Mock()), "brave")

    locator = _FakeFormLocator()
    _browser, _page, chromium = _install_fake_playwright(monkeypatch, locator)
    BrowserReader().fill_empty_public_form_field(
        "https://example.com/form",
        "Contact",
        "value",
        channel="msedge",
    )
    chromium.launch.assert_called_once_with(headless=True, channel="msedge")


def test_visible_browser_session_manages_isolated_public_tabs(monkeypatch):
    browser, chromium, managers = _install_fake_browser_session(monkeypatch)

    with BrowserTabSession(BrowserReader(), channel="msedge") as session:
        first = session.open_tab("https://example.com")
        second = session.open_tab("https://example.org")
        assert first["tab_id"] == "tab-1"
        assert second["tab_id"] == "tab-2"
        assert first["trust"] == "untrusted_external_content"
        assert "example.com" in first["text"]
        navigated = session.navigate_tab("tab-1", "https://example.net/next")
        assert navigated["url"] == "https://example.net/next"
        assert session.read_tab("tab-1")["tab_id"] == "tab-1"
        assert [tab["tab_id"] for tab in session.list_tabs()] == ["tab-1", "tab-2"]
        session.close_tab("tab-2")
        with pytest.raises(KeyError, match="not found"):
            session.read_tab("tab-2")

        class Route:
            aborted = False
            continued = False

            def abort(self):
                self.aborted = True

            def continue_(self):
                self.continued = True

        route = Route()
        browser.context.request_guard(
            route, SimpleNamespace(method="POST", url="https://example.com/send")
        )
        assert route.aborted and not route.continued

    assert browser.context.options == {
        "accept_downloads": False,
        "java_script_enabled": False,
    }
    assert browser.context.closed and browser.closed and managers[0].exited
    chromium.launch.assert_called_once_with(headless=False, channel="msedge")


def test_visible_browser_session_enforces_tab_limit(monkeypatch):
    _browser, _chromium, _managers = _install_fake_browser_session(monkeypatch)
    with BrowserTabSession(BrowserReader()) as session:
        for index in range(BrowserTabSession.MAX_TABS):
            session.open_tab(f"https://example{index}.com")
        with pytest.raises(ValueError, match="at most 8 tabs"):
            session.open_tab("https://last.example")


def test_public_form_tool_is_modifying_and_requires_registry_approval(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    reader = Mock()
    reader.fill_empty_public_form_field.return_value = {
        "filled": True,
        "submitted": False,
    }
    registry = ToolRegistry(database)
    register_safe_browser_tools(registry, reader)
    tool = next(
        spec for spec in registry.list_tools()
        if spec.name == "fill_empty_public_form_field"
    )
    assert tool.risk is RiskLevel.MODIFICATION
    arguments = {
        "url": "https://example.com/form",
        "label": "Email",
        "text": "person@example.com",
    }
    with pytest.raises(Exception):
        registry.execute("fill_empty_public_form_field", arguments)
    result = registry.execute(
        "fill_empty_public_form_field",
        arguments,
        confirm=lambda *_args: True,
    )
    assert result.verified
