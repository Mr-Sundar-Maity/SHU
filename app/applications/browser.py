"""Isolated Playwright page reader and approval-gated public form preparation."""

from __future__ import annotations

import ipaddress
import hashlib
import os
import socket
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from app.security.policy import RiskLevel
from app.security.registry import ToolRegistry, ToolSpec


class _TransientHTTPStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Public page returned transient HTTP status {status_code}")


class BrowserReader:
    BROWSER_CHANNELS = frozenset({"chromium", "chrome", "msedge", "brave"})

    def __init__(self, *, timeout_ms: int = 15_000, max_text_chars: int = 50_000) -> None:
        if timeout_ms < 1_000 or max_text_chars < 1_000:
            raise ValueError("Browser limits are too small")
        self.timeout_ms = timeout_ms
        self.max_text_chars = max_text_chars

    def read_page(self, url: str, channel: str = "chromium") -> dict[str, str]:
        target = self.validate_url(url)
        channel = self.validate_channel(channel)
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError("Install Playwright to use browser reading") from error

        try:
            with sync_playwright() as playwright:
                browser = self._launch_browser(playwright, channel)
                context = browser.new_context(
                    accept_downloads=False,
                    java_script_enabled=False,
                )
                context.route("**/*", self._guard_form_request)
                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.on("dialog", lambda dialog: dialog.dismiss())
                try:
                    response = page.goto(
                        target,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                    status_code = getattr(response, "status", None)
                    if (
                        isinstance(status_code, int)
                        and not isinstance(status_code, bool)
                        and (
                            status_code in {408, 425, 429}
                            or 500 <= status_code <= 599
                        )
                    ):
                        raise _TransientHTTPStatusError(status_code)
                    final_url = self.validate_resolved_url(page.url)
                    title = page.title()[:500]
                    body_text = page.locator("body").inner_text(timeout=self.timeout_ms)
                    return {
                        "url": final_url,
                        "title": title,
                        "text": body_text[: self.max_text_chars],
                        "browser_channel": channel,
                        "trust": "untrusted_external_content",
                    }
                except PlaywrightTimeoutError as error:
                    raise TimeoutError("Browser navigation timed out") from error
                finally:
                    context.close()
                    browser.close()
        except Exception as error:
            if isinstance(
                error,
                (
                    TimeoutError,
                    ValueError,
                    PermissionError,
                    FileNotFoundError,
                    _TransientHTTPStatusError,
                ),
            ):
                raise
            install_hint = (
                "Run 'python -m playwright install chromium'."
                if channel == "chromium"
                else f"Verify that {channel} is installed and compatible with Playwright."
            )
            raise RuntimeError(
                f"{channel} browser could not open the page. {install_hint}"
            ) from error

    def fill_empty_public_form_field(
        self,
        url: str,
        label: str,
        text: str,
        channel: str = "chromium",
    ) -> dict[str, Any]:
        """Fill one empty labeled field on a stateless, script-disabled public page."""
        target = self.validate_url(url)
        channel = self.validate_channel(channel)
        if not label or len(label) > 200 or not text or len(text) > 2_000:
            raise ValueError("A field label and text of at most 2000 characters are required")
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError("Install Playwright to use browser form preparation") from error

        browser = context = None
        try:
            with sync_playwright() as playwright:
                browser = self._launch_browser(playwright, channel)
                context = browser.new_context(
                    accept_downloads=False,
                    java_script_enabled=False,
                )
                context.route("**/*", self._guard_form_request)
                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.on("dialog", lambda dialog: dialog.dismiss())
                page.goto(target, wait_until="domcontentloaded", timeout=self.timeout_ms)
                final_url = self.validate_resolved_url(page.url)
                locator = page.get_by_label(label, exact=True)
                if locator.count() != 1:
                    raise ValueError("The accessible field label must match exactly one control")
                if not locator.is_visible() or not locator.is_enabled() or not locator.is_editable():
                    raise PermissionError("The labeled control is not visible and editable")
                metadata = locator.evaluate(
                    "el => ({tag: el.tagName.toLowerCase(), type: el.getAttribute('type'), "
                    "readOnly: Boolean(el.readOnly)})"
                )
                tag = str(metadata.get("tag", "")).lower()
                input_type = str(metadata.get("type") or "text").lower()
                allowed_types = {"text", "email", "search", "tel", "url", "number"}
                if tag == "textarea":
                    pass
                elif tag != "input" or input_type not in allowed_types:
                    raise PermissionError("Only plain text, email, search, phone, URL or number fields are allowed")
                if metadata.get("readOnly"):
                    raise PermissionError("Read-only controls cannot be filled")
                if locator.input_value() != "":
                    raise PermissionError("SHU only fills an empty field")
                locator.fill(text, timeout=self.timeout_ms)
                if locator.input_value() != text:
                    raise IOError("Browser field value did not match the requested text")
                if self.validate_resolved_url(page.url) != final_url:
                    raise RuntimeError("The page navigated during form preparation")
                return {
                    "url": final_url,
                    "label": label,
                    "text_length": len(text),
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "filled": True,
                    "submitted": False,
                    "browser_channel": channel,
                    "trust": "untrusted_external_page",
                }
        except PlaywrightTimeoutError as error:
            raise TimeoutError("Browser form preparation timed out") from error
        except (TimeoutError, ValueError, PermissionError, RuntimeError, IOError, FileNotFoundError):
            raise
        except Exception as error:
            raise RuntimeError("Browser could not safely prepare the public form field") from error
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

    @staticmethod
    def validate_channel(channel: str) -> str:
        if not isinstance(channel, str) or channel not in BrowserReader.BROWSER_CHANNELS:
            raise ValueError("Browser channel must be chromium, chrome, msedge or brave")
        return channel

    @staticmethod
    def _launch_browser(playwright, channel: str, *, headless: bool = True):
        options = {"headless": headless}
        if channel == "brave":
            executable = BrowserReader.find_brave_executable()
            if executable is None:
                raise FileNotFoundError(
                    "Brave is not installed in a standard Windows application directory"
                )
            options["executable_path"] = str(executable)
        elif channel != "chromium":
            options["channel"] = channel
        return playwright.chromium.launch(**options)

    @staticmethod
    def find_brave_executable() -> Path | None:
        """Find a standard per-machine or per-user Brave installation."""
        roots = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        relative = Path("BraveSoftware") / "Brave-Browser" / "Application" / "brave.exe"
        for root in roots:
            if not root:
                continue
            candidate = Path(root) / relative
            if candidate.is_file():
                return candidate.resolve()
        return None

    @staticmethod
    def validate_url(url: str) -> str:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only HTTP and HTTPS pages are supported")
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("A public URL without embedded credentials is required")
        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise PermissionError("Local and .local network addresses are blocked")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise PermissionError("Private and reserved IP addresses are blocked")
        return url.strip()

    @classmethod
    def validate_resolved_url(cls, url: str) -> str:
        """Reject hostnames that resolve to loopback, private or reserved IPs."""
        target = cls.validate_url(url)
        parsed = urlparse(target)
        host = parsed.hostname
        if host is None:
            raise ValueError("A public host is required")
        try:
            answers = socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError as error:
            raise PermissionError("The browser host could not be resolved safely") from error
        addresses = {ipaddress.ip_address(answer[4][0]) for answer in answers}
        if not addresses or any(not address.is_global for address in addresses):
            raise PermissionError("The browser host resolves to a private or reserved address")
        return target

    @classmethod
    def _guard_request(cls, route, request) -> None:
        try:
            cls.validate_resolved_url(request.url)
        except (ValueError, PermissionError):
            route.abort()
            return
        route.continue_()

    @classmethod
    def _guard_form_request(cls, route, request) -> None:
        if request.method.upper() not in {"GET", "HEAD"}:
            route.abort()
            return
        cls._guard_request(route, request)


class BrowserTabSession:
    """A visible, short-lived collection of stateless public-page browser tabs."""

    MAX_TABS = 8

    def __init__(self, reader: BrowserReader, channel: str = "chromium") -> None:
        self.reader = reader
        self.channel = BrowserReader.validate_channel(channel)
        self._sync_context = None
        self._playwright = None
        self._playwright_entered = False
        self._browser = None
        self._context = None
        self._tabs: dict[str, Any] = {}
        self._next_id = 1

    def __enter__(self) -> "BrowserTabSession":
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError("Install Playwright to manage browser tabs") from error
        self._timeout_error = PlaywrightTimeoutError
        self._sync_context = sync_playwright()
        try:
            self._playwright = self._sync_context.__enter__()
            self._playwright_entered = True
            self._browser = self.reader._launch_browser(
                self._playwright, self.channel, headless=False
            )
            self._context = self._browser.new_context(
                accept_downloads=False,
                java_script_enabled=False,
            )
            self._context.route("**/*", BrowserReader._guard_form_request)
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, exc_type, exc, traceback) -> bool:
        for resource in (self._context, self._browser):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        self._context = None
        self._browser = None
        if self._sync_context is not None:
            try:
                if self._playwright_entered:
                    self._sync_context.__exit__(exc_type, exc, traceback)
            finally:
                self._sync_context = None
                self._playwright = None
                self._playwright_entered = False
        return False

    def open_tab(self, url: str) -> dict[str, str]:
        self._require_open()
        if len(self._tabs) >= self.MAX_TABS:
            raise ValueError(f"A SHU browser session supports at most {self.MAX_TABS} tabs")
        page = self._context.new_page()
        page.set_default_timeout(self.reader.timeout_ms)
        page.on("dialog", lambda dialog: dialog.dismiss())
        tab_id = f"tab-{self._next_id}"
        self._next_id += 1
        try:
            result = self._navigate_page(page, url, tab_id)
        except BaseException:
            page.close()
            raise
        self._tabs[tab_id] = page
        return result

    def navigate_tab(self, tab_id: str, url: str) -> dict[str, str]:
        page = self._get_page(tab_id)
        return self._navigate_page(page, url, tab_id)

    def read_tab(self, tab_id: str) -> dict[str, str]:
        self._require_open()
        page = self._get_page(tab_id)
        final_url = self.reader.validate_resolved_url(page.url)
        return {
            "tab_id": tab_id,
            "url": final_url,
            "title": page.title()[:500],
            "text": page.locator("body").inner_text(timeout=self.reader.timeout_ms)[
                : self.reader.max_text_chars
            ],
            "browser_channel": self.channel,
            "trust": "untrusted_external_content",
        }

    def list_tabs(self) -> list[dict[str, str]]:
        self._require_open()
        result = []
        for tab_id, page in self._tabs.items():
            result.append(
                {
                    "tab_id": tab_id,
                    "url": page.url[:2_000],
                    "title": page.title()[:500],
                    "browser_channel": self.channel,
                }
            )
        return result

    def close_tab(self, tab_id: str) -> None:
        page = self._get_page(tab_id)
        page.close()
        del self._tabs[tab_id]

    def _navigate_page(self, page, url: str, tab_id: str) -> dict[str, str]:
        target = self.reader.validate_resolved_url(url)
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=self.reader.timeout_ms)
        except self._timeout_error as error:
            raise TimeoutError("Browser tab navigation timed out") from error
        return self._page_result(page, tab_id)

    def _page_result(self, page, tab_id: str) -> dict[str, str]:
        final_url = self.reader.validate_resolved_url(page.url)
        return {
            "tab_id": tab_id,
            "url": final_url,
            "title": page.title()[:500],
            "text": page.locator("body").inner_text(timeout=self.reader.timeout_ms)[
                : self.reader.max_text_chars
            ],
            "browser_channel": self.channel,
            "trust": "untrusted_external_content",
        }

    def _get_page(self, tab_id: str):
        self._require_open()
        if tab_id not in self._tabs:
            raise KeyError("Browser tab not found in this session")
        return self._tabs[tab_id]

    def _require_open(self) -> None:
        if self._context is None or self._browser is None:
            raise RuntimeError("Browser tab session is not open")


def register_safe_browser_tools(registry: ToolRegistry, reader: BrowserReader) -> None:
    """Expose browser reading and safe form preparation through tool policy."""

    def validate(arguments: Mapping[str, Any]) -> dict[str, str]:
        if set(arguments) - {"url", "channel"} or "url" not in arguments:
            raise ValueError("Web reading requires a URL and optional browser channel")
        url = arguments["url"]
        if not isinstance(url, str) or len(url) > 2_000:
            raise TypeError("URL must be text of at most 2000 characters")
        channel = BrowserReader.validate_channel(arguments.get("channel", "chromium"))
        return {"url": BrowserReader.validate_url(url), "channel": channel}

    registry.register(
        ToolSpec(
            name="read_public_webpage",
            description="Read a public web page in Chromium, Chrome, Edge or best-effort Brave; page content is untrusted",
            risk=RiskLevel.READ_ONLY,
            handler=reader.read_page,
            validator=validate,
            estimate_seconds=12,
            resources=("browser", "network"),
            retry_limit=2,
        )
    )

    def validate_form_fill(arguments: Mapping[str, Any]) -> dict[str, str]:
        required = {"url", "label", "text"}
        if not required <= set(arguments) or set(arguments) - {*required, "channel"} or not all(
            isinstance(arguments[key], str) for key in required
        ):
            raise ValueError("Public form preparation requires url, label, text and optional channel")
        url = arguments["url"]
        label = arguments["label"].strip()
        text = arguments["text"]
        if len(url) > 2_000 or not label or len(label) > 200 or not text or len(text) > 2_000:
            raise ValueError("URL, label or text is empty or exceeds its safety limit")
        channel = BrowserReader.validate_channel(arguments.get("channel", "chromium"))
        return {
            "url": BrowserReader.validate_url(url),
            "label": label,
            "text": text,
            "channel": channel,
        }

    registry.register(
        ToolSpec(
            name="fill_empty_public_form_field",
            description="Prepare one empty labeled field on a public page; scripts and submit are blocked",
            risk=RiskLevel.MODIFICATION,
            handler=reader.fill_empty_public_form_field,
            validator=validate_form_fill,
            verifier=lambda result, _args: bool(
                isinstance(result, dict)
                and result.get("filled") is True
                and result.get("submitted") is False
            ),
            estimate_seconds=15,
            resources=("browser", "network"),
        )
    )
