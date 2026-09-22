"""Allowlisted Playwright session with hard execution budgets."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from types import TracebackType
from urllib.parse import SplitResult, urlsplit

from playwright.async_api import (
    Browser,
    BrowserContext,
    Download,
    Page,
    Playwright,
    Route,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from qa_agent_lm.browser.errors import (
    DownloadBlockedError,
    ExternalProtocolBlockedError,
    NavigationTimeoutError,
    OriginNotAllowedError,
    SessionClosedError,
    StepLimitExceededError,
    WallClockTimeoutError,
)


class SessionState(Enum):
    NEW = "new"
    ACTIVE = "active"
    CLOSED = "closed"


def _origin(parts: SplitResult) -> str:
    if parts.scheme not in {"http", "https"} or parts.hostname is None:
        raise ExternalProtocolBlockedError(f"Blocked URL scheme: {parts.scheme or '(none)'}")
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError("Origin has an invalid port") from error
    default_port = 80 if parts.scheme == "http" else 443
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parts.scheme.lower()}://{host}{suffix}"


def _configured_origin(value: str) -> str:
    parts = urlsplit(value)
    if not value or parts.username is not None or parts.password is not None:
        raise ValueError("Allowed origins must not be empty or contain credentials")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError("Allowed origins must not contain a path, query, or fragment")
    try:
        return _origin(parts)
    except ExternalProtocolBlockedError as error:
        raise ValueError("Allowed origins must use HTTP or HTTPS") from error


@dataclass(frozen=True)
class BrowserSessionConfig:
    allowed_origins: tuple[str, ...]
    navigation_timeout_ms: int = 10_000
    wall_clock_timeout_s: float = 60.0
    max_actions: int = 50
    headless: bool = True
    executable_path: str | None = field(
        default_factory=lambda: os.getenv("QA_AGENT_BROWSER_EXECUTABLE")
    )
    _canonical_origins: frozenset[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.allowed_origins:
            raise ValueError("At least one allowed origin is required")
        if self.navigation_timeout_ms <= 0:
            raise ValueError("navigation_timeout_ms must be positive")
        if self.wall_clock_timeout_s <= 0:
            raise ValueError("wall_clock_timeout_s must be positive")
        if self.max_actions <= 0:
            raise ValueError("max_actions must be positive")
        object.__setattr__(
            self,
            "_canonical_origins",
            frozenset(_configured_origin(value) for value in self.allowed_origins),
        )


@dataclass(frozen=True)
class NavigationResult:
    final_url: str
    title: str


class BrowserSession:
    def __init__(self, config: BrowserSessionConfig) -> None:
        self.config = config
        self.state = SessionState.NEW
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._started_at: float | None = None
        self._actions = 0
        self._blocked_url: str | None = None
        self._download_seen = False
        self._lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def __aenter__(self) -> BrowserSession:
        return await self.start()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def start(self) -> BrowserSession:
        if self.state is not SessionState.NEW:
            raise SessionClosedError("Browser session can only be started once")
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.config.headless,
                executable_path=self.config.executable_path,
            )
            self._context = await self._browser.new_context(accept_downloads=False)
            await self._context.route("**/*", self._guard_route)
            self._page = await self._context.new_page()
            self._page.on("download", self._on_download)
            self._context.on("page", self._on_new_page)
            self._started_at = monotonic()
            self.state = SessionState.ACTIVE
            return self
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        if self.state is SessionState.CLOSED:
            return
        self.state = SessionState.CLOSED
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

    async def navigate(self, url: str) -> NavigationResult:
        async with self._lock:
            page = self._active_page()
            remaining = self._begin_action()
            self._ensure_allowed(url)
            self._blocked_url = None
            self._download_seen = False
            timeout_ms = min(self.config.navigation_timeout_ms, max(1, int(remaining * 1000)))
            try:
                async with asyncio.timeout(remaining):
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except PlaywrightTimeoutError as error:
                raise NavigationTimeoutError(f"Navigation timed out: {url}") from error
            except TimeoutError as error:
                raise WallClockTimeoutError(
                    "Browser session exceeded its wall-clock budget"
                ) from error
            except PlaywrightError as error:
                await asyncio.sleep(0)
                if self._blocked_url is not None:
                    raise OriginNotAllowedError(
                        f"Navigation left the allowed origins: {self._blocked_url}"
                    ) from error
                if self._download_seen or "Download is starting" in str(error):
                    raise DownloadBlockedError(f"Downloads are disabled: {url}") from error
                raise
            if self._blocked_url is not None:
                raise OriginNotAllowedError(
                    f"Navigation left the allowed origins: {self._blocked_url}"
                )
            self._ensure_allowed(page.url)
            return NavigationResult(final_url=page.url, title=await page.title())

    def _active_page(self) -> Page:
        if self.state is not SessionState.ACTIVE or self._page is None:
            raise SessionClosedError("Browser session is not active")
        return self._page

    def _begin_action(self) -> float:
        if self._actions >= self.config.max_actions:
            raise StepLimitExceededError("Browser session exceeded its action limit")
        self._actions += 1
        if self._started_at is None:
            raise SessionClosedError("Browser session is not active")
        remaining = self.config.wall_clock_timeout_s - (monotonic() - self._started_at)
        if remaining <= 0:
            raise WallClockTimeoutError("Browser session exceeded its wall-clock budget")
        return remaining

    def _ensure_allowed(self, url: str) -> None:
        parts = urlsplit(url)
        origin = _origin(parts)
        if origin not in self.config._canonical_origins:
            raise OriginNotAllowedError(f"Origin is not allowed: {origin}")

    async def _guard_route(self, route: Route) -> None:
        request = route.request
        if urlsplit(request.url).scheme in {"http", "https"}:
            try:
                self._ensure_allowed(request.url)
            except OriginNotAllowedError:
                self._blocked_url = request.url
                await route.abort("blockedbyclient")
                return
        await route.continue_()

    def _on_download(self, download: Download) -> None:
        self._download_seen = True
        self._track_task(asyncio.create_task(download.cancel()))

    def _on_new_page(self, page: Page) -> None:
        if self._page is not None and page is not self._page:
            self._track_task(asyncio.create_task(page.close()))

    def _track_task(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
