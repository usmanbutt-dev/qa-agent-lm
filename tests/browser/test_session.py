from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qa_agent_lm.browser.errors import (
    DownloadBlockedError,
    ExternalProtocolBlockedError,
    OriginNotAllowedError,
    SessionClosedError,
    StepLimitExceededError,
    WallClockTimeoutError,
)
from qa_agent_lm.browser.session import BrowserSession, BrowserSessionConfig, SessionState


class SiteHandler(BaseHTTPRequestHandler):
    redirect_target = ""

    def do_GET(self) -> None:
        if self.path == "/ok":
            body = b"<html><title>Allowed page</title><body>ok</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", self.redirect_target)
            self.end_headers()
            return
        if self.path == "/download":
            body = b"not allowed"
            self.send_response(200)
            self.send_header("Content-Disposition", 'attachment; filename="blocked.txt"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = str(server.server_address[0])
    port = int(server.server_address[1])
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def origins() -> Iterator[tuple[str, str]]:
    with serve(SiteHandler) as allowed, serve(SiteHandler) as denied:
        SiteHandler.redirect_target = f"{denied}/ok"
        yield allowed, denied


@pytest.mark.asyncio
async def test_allowed_navigation_and_deterministic_cleanup(origins: tuple[str, str]) -> None:
    allowed, _ = origins
    session = BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,)))

    async with session:
        result = await session.navigate(f"{allowed}/ok")
        assert result.final_url == f"{allowed}/ok"
        assert result.title == "Allowed page"
    assert session.state is SessionState.CLOSED
    await session.close()
    assert session.state is SessionState.CLOSED


@pytest.mark.asyncio
async def test_direct_navigation_outside_allowlist_is_rejected(
    origins: tuple[str, str],
) -> None:
    allowed, denied = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        with pytest.raises(OriginNotAllowedError):
            await session.navigate(f"{denied}/ok")


@pytest.mark.asyncio
async def test_redirect_outside_allowlist_is_rejected(origins: tuple[str, str]) -> None:
    allowed, _ = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        with pytest.raises(OriginNotAllowedError):
            await session.navigate(f"{allowed}/redirect")


@pytest.mark.asyncio
async def test_external_protocol_is_rejected(origins: tuple[str, str]) -> None:
    allowed, _ = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        with pytest.raises(ExternalProtocolBlockedError):
            await session.navigate("file:///etc/passwd")


@pytest.mark.asyncio
async def test_download_navigation_is_rejected(origins: tuple[str, str]) -> None:
    allowed, _ = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        with pytest.raises(DownloadBlockedError):
            await session.navigate(f"{allowed}/download")


@pytest.mark.asyncio
async def test_action_budget_counts_failed_attempts(origins: tuple[str, str]) -> None:
    allowed, denied = origins
    config = BrowserSessionConfig(allowed_origins=(allowed,), max_actions=1)
    async with BrowserSession(config) as session:
        with pytest.raises(OriginNotAllowedError):
            await session.navigate(f"{denied}/ok")
        with pytest.raises(StepLimitExceededError):
            await session.navigate(f"{allowed}/ok")


@pytest.mark.asyncio
async def test_expired_wall_clock_budget_is_rejected(origins: tuple[str, str]) -> None:
    allowed, _ = origins
    config = BrowserSessionConfig(allowed_origins=(allowed,), wall_clock_timeout_s=0.01)
    async with BrowserSession(config) as session:
        await asyncio.sleep(0.02)
        with pytest.raises(WallClockTimeoutError):
            await session.navigate(f"{allowed}/ok")


@pytest.mark.asyncio
async def test_navigation_after_close_is_rejected(origins: tuple[str, str]) -> None:
    allowed, _ = origins
    session = BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,)))
    await session.start()
    await session.close()

    with pytest.raises(SessionClosedError):
        await session.navigate(f"{allowed}/ok")


@pytest.mark.parametrize(
    "origin",
    ["", "ftp://example.test", "https://user:secret@example.test", "https://example.test/path"],
)
def test_invalid_allowed_origin_is_rejected(origin: str) -> None:
    with pytest.raises(ValueError):
        BrowserSessionConfig(allowed_origins=(origin,))
