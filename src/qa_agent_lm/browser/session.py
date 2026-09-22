"""Allowlisted Playwright session with hard execution budgets."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from time import monotonic
from types import TracebackType
from typing import TypedDict, cast
from urllib.parse import SplitResult, urlsplit

from playwright.async_api import (
    Browser,
    BrowserContext,
    Download,
    ElementHandle,
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
    ActionTimeoutError,
    DownloadBlockedError,
    ExternalProtocolBlockedError,
    InvalidRequestError,
    NavigationTimeoutError,
    OriginNotAllowedError,
    SessionClosedError,
    StaleElementReferenceError,
    StepLimitExceededError,
    TargetNotFoundError,
    WallClockTimeoutError,
)
from qa_agent_lm.browser.evidence import (
    DiagnosticsResult,
    EvidenceCollector,
    ScreenshotResult,
)

_ELEMENT_REF = re.compile(r"^el_(\d{6})_(\d{4})$")
_ARTIFACT_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,79}$")
_CONTRACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_HUMAN_HELP_REASONS = {
    "ambiguous_goal",
    "missing_information",
    "sensitive_action",
    "blocked",
    "other",
}
_INTERACTIVE_SELECTOR = ",".join(
    (
        "a[href]",
        "button",
        "input:not([type=hidden])",
        "select",
        "textarea",
        "[role]",
        "[contenteditable=true]",
        '[tabindex]:not([tabindex="-1"])',
    )
)


class _ElementMetadata(TypedDict):
    role: str
    name: str
    disabled: bool


class _ClickTarget(TypedDict):
    destination: str
    download: bool


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
    action_timeout_ms: int = 5_000
    wall_clock_timeout_s: float = 60.0
    max_actions: int = 50
    artifact_dir: Path = Path("artifacts/browser")
    secret_values: tuple[str, ...] = ()
    diagnostic_capacity: int = 200
    max_artifacts: int = 20
    max_screenshot_bytes: int = 5_000_000
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
        if self.action_timeout_ms <= 0:
            raise ValueError("action_timeout_ms must be positive")
        if self.wall_clock_timeout_s <= 0:
            raise ValueError("wall_clock_timeout_s must be positive")
        if self.max_actions <= 0:
            raise ValueError("max_actions must be positive")
        if not 1 <= self.diagnostic_capacity <= 200:
            raise ValueError("diagnostic_capacity must be between 1 and 200")
        if self.max_artifacts <= 0 or self.max_screenshot_bytes <= 0:
            raise ValueError("artifact limits must be positive")
        object.__setattr__(
            self,
            "_canonical_origins",
            frozenset(_configured_origin(value) for value in self.allowed_origins),
        )


@dataclass(frozen=True)
class NavigationResult:
    final_url: str
    title: str


@dataclass(frozen=True)
class ObservedElement:
    element_ref: str
    role: str
    name: str
    disabled: bool


@dataclass(frozen=True)
class ObservationResult:
    observation_id: str
    url: str
    elements: tuple[ObservedElement, ...]
    truncated: bool


@dataclass(frozen=True)
class InteractionResult:
    navigation_occurred: bool


@dataclass(frozen=True)
class TypeResult:
    characters_written: int


@dataclass(frozen=True)
class FinishResult:
    outcome: str
    state: str = "finished"


@dataclass(frozen=True)
class HumanHelpResult:
    state: str = "paused"


class BrowserSession:
    def __init__(self, config: BrowserSessionConfig) -> None:
        self.config = config
        self.state = SessionState.NEW
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._evidence: EvidenceCollector | None = None
        self._started_at: float | None = None
        self._actions = 0
        self._observation_generation = 0
        self._active_observation_generation: int | None = None
        self._elements: dict[str, ElementHandle] = {}
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
            self._evidence = EvidenceCollector(
                self._page,
                artifact_dir=self.config.artifact_dir,
                secret_values=self.config.secret_values,
                diagnostic_capacity=self.config.diagnostic_capacity,
                max_artifacts=self.config.max_artifacts,
                max_screenshot_bytes=self.config.max_screenshot_bytes,
            )
            self._evidence.attach()
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
        await self._invalidate_observation()
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
            await self._invalidate_observation()
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

    async def inspect(
        self,
        *,
        scope_ref: str | None = None,
        max_elements: int = 100,
        include_text: bool = True,
    ) -> ObservationResult:
        async with self._lock:
            page = self._active_page()
            remaining = self._begin_action()
            if not 1 <= max_elements <= 200:
                raise InvalidRequestError("max_elements must be between 1 and 200")
            scope = self._resolve_element(scope_ref) if scope_ref is not None else page
            timeout = min(self.config.action_timeout_ms / 1000, remaining)
            try:
                async with asyncio.timeout(timeout):
                    candidates = await scope.query_selector_all(_INTERACTIVE_SELECTOR)
                    visible: list[tuple[ElementHandle, _ElementMetadata]] = []
                    processed_count = 0
                    for handle in candidates:
                        processed_count += 1
                        if not await handle.is_visible():
                            await handle.dispose()
                            continue
                        metadata = cast(
                            _ElementMetadata,
                            await handle.evaluate(
                                """(element, includeText) => {
                                  const tag = element.tagName.toLowerCase();
                                  const inputType = (element.getAttribute('type') || 'text').toLowerCase();
                                  const implicitRoles = {
                                    a: 'link', button: 'button', select: 'combobox',
                                    textarea: 'textbox'
                                  };
                                  let role = element.getAttribute('role') || implicitRoles[tag] || tag;
                                  if (tag === 'input') {
                                    role = ['button', 'submit', 'reset'].includes(inputType)
                                      ? 'button'
                                      : ['checkbox', 'radio'].includes(inputType) ? inputType : 'textbox';
                                  }
                                  const label = element.labels?.[0]?.textContent?.trim() || '';
                                  const text = includeText ? (element.textContent || '').trim() : '';
                                  const name = element.getAttribute('aria-label') || label ||
                                    element.getAttribute('placeholder') || text ||
                                    element.getAttribute('name') || '';
                                  return {
                                    role: String(role).slice(0, 80),
                                    name: String(name).replace(/\\s+/g, ' ').slice(0, 500),
                                    disabled: element.matches(':disabled') ||
                                      element.getAttribute('aria-disabled') === 'true'
                                  };
                                }""",
                                include_text,
                            ),
                        )
                        visible.append((handle, metadata))
                        if len(visible) > max_elements:
                            break
                    for handle in candidates[processed_count:]:
                        await handle.dispose()
                    retained = visible[:max_elements]
                    for handle, _ in visible[max_elements:]:
                        await handle.dispose()
            except TimeoutError as error:
                raise ActionTimeoutError("Inspection timed out") from error

            await self._invalidate_observation()
            self._observation_generation += 1
            generation = self._observation_generation
            self._active_observation_generation = generation
            observed: list[ObservedElement] = []
            for index, (handle, metadata) in enumerate(retained, start=1):
                element_ref = f"el_{generation:06d}_{index:04d}"
                self._elements[element_ref] = handle
                observed.append(ObservedElement(element_ref=element_ref, **metadata))
            return ObservationResult(
                observation_id=f"obs_{generation:06d}",
                url=page.url,
                elements=tuple(observed),
                truncated=len(visible) > max_elements,
            )

    async def click(self, element_ref: str) -> InteractionResult:
        async with self._lock:
            page = self._active_page()
            remaining = self._begin_action()
            target = self._resolve_element(element_ref)
            await self._validate_click_target(target)
            before_url = page.url
            await self._perform_interaction(
                lambda timeout: target.click(timeout=timeout), remaining, "Click"
            )
            return InteractionResult(navigation_occurred=page.url != before_url)

    async def type(self, element_ref: str, text: str, *, replace: bool = True) -> TypeResult:
        async with self._lock:
            self._active_page()
            remaining = self._begin_action()
            if not 1 <= len(text) <= 10_000:
                raise InvalidRequestError("text must contain between 1 and 10000 characters")
            target = self._resolve_element(element_ref)
            action = target.fill if replace else target.type
            await self._perform_interaction(
                lambda timeout: action(text, timeout=timeout), remaining, "Text entry"
            )
            return TypeResult(characters_written=len(text))

    async def read_diagnostics(
        self, channels: tuple[str, ...], *, max_entries: int = 50
    ) -> DiagnosticsResult:
        async with self._lock:
            self._active_page()
            self._begin_action()
            if self._evidence is None:
                raise SessionClosedError("Browser session is not active")
            return self._evidence.read(channels, max_entries)

    async def take_screenshot(self, label: str, *, full_page: bool = False) -> ScreenshotResult:
        async with self._lock:
            self._active_page()
            remaining = self._begin_action()
            if _ARTIFACT_LABEL.fullmatch(label) is None:
                raise InvalidRequestError("Screenshot label is invalid")
            if self._evidence is None:
                raise SessionClosedError("Browser session is not active")
            timeout_ms = min(self.config.action_timeout_ms, max(1, int(remaining * 1000)))
            try:
                async with asyncio.timeout(remaining):
                    return await self._evidence.screenshot(
                        label, full_page=full_page, timeout_ms=timeout_ms
                    )
            except PlaywrightTimeoutError as error:
                raise ActionTimeoutError("Screenshot timed out") from error
            except TimeoutError as error:
                raise WallClockTimeoutError(
                    "Browser session exceeded its wall-clock budget"
                ) from error

    async def finish(
        self, outcome: str, summary: str, evidence_ids: tuple[str, ...]
    ) -> FinishResult:
        async with self._lock:
            self._active_page()
            self._begin_action()
            if outcome not in {"pass", "fail"}:
                raise InvalidRequestError("outcome must be pass or fail")
            if not 1 <= len(summary) <= 2000:
                raise InvalidRequestError("summary must contain between 1 and 2000 characters")
            if len(evidence_ids) > 50 or len(set(evidence_ids)) != len(evidence_ids):
                raise InvalidRequestError("evidence_ids must contain at most 50 unique values")
            if any(_CONTRACT_ID.fullmatch(value) is None for value in evidence_ids):
                raise InvalidRequestError("evidence_ids contains an invalid identifier")
            result = FinishResult(outcome=outcome)
            await self.close()
            return result

    async def request_human_help(self, reason: str, question: str) -> HumanHelpResult:
        async with self._lock:
            self._active_page()
            self._begin_action()
            if reason not in _HUMAN_HELP_REASONS:
                raise InvalidRequestError("reason is not a supported human-help reason")
            if not 1 <= len(question) <= 1000:
                raise InvalidRequestError("question must contain between 1 and 1000 characters")
            result = HumanHelpResult()
            await self.close()
            return result

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

    def _resolve_element(self, element_ref: str) -> ElementHandle:
        match = _ELEMENT_REF.fullmatch(element_ref)
        if match is None:
            raise TargetNotFoundError(f"Unknown element reference: {element_ref}")
        generation = int(match.group(1))
        if generation != self._active_observation_generation:
            raise StaleElementReferenceError(
                f"Element reference is not from the latest observation: {element_ref}"
            )
        try:
            return self._elements[element_ref]
        except KeyError as error:
            raise TargetNotFoundError(f"Unknown element reference: {element_ref}") from error

    async def _perform_interaction(
        self,
        action: Callable[[int], Awaitable[None]],
        remaining: float,
        label: str,
    ) -> None:
        self._blocked_url = None
        self._download_seen = False
        timeout_ms = min(self.config.action_timeout_ms, max(1, int(remaining * 1000)))
        try:
            async with asyncio.timeout(remaining):
                await action(timeout_ms)
        except PlaywrightTimeoutError as error:
            raise ActionTimeoutError(f"{label} timed out") from error
        except TimeoutError as error:
            raise WallClockTimeoutError("Browser session exceeded its wall-clock budget") from error
        except PlaywrightError as error:
            if self._blocked_url is not None:
                raise OriginNotAllowedError(
                    f"Interaction left the allowed origins: {self._blocked_url}"
                ) from error
            if self._download_seen:
                raise DownloadBlockedError("Downloads are disabled") from error
            raise TargetNotFoundError(f"{label} target is no longer available") from error
        if self._blocked_url is not None:
            raise OriginNotAllowedError(
                f"Interaction left the allowed origins: {self._blocked_url}"
            )
        if self._download_seen:
            raise DownloadBlockedError("Downloads are disabled")

    async def _validate_click_target(self, target: ElementHandle) -> None:
        try:
            details = cast(
                _ClickTarget,
                await target.evaluate(
                    """element => {
                      const form = element.form || element.closest('form');
                      return {
                        destination: element.href || element.formAction || form?.action || '',
                        download: element.hasAttribute('download')
                      };
                    }"""
                ),
            )
        except PlaywrightError as error:
            raise TargetNotFoundError("Click target is no longer available") from error
        if details["download"]:
            raise DownloadBlockedError("Downloads are disabled")
        if details["destination"]:
            self._ensure_allowed(details["destination"])

    async def _invalidate_observation(self) -> None:
        handles = tuple(self._elements.values())
        self._elements.clear()
        self._active_observation_generation = None
        for handle in handles:
            await handle.dispose()

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
