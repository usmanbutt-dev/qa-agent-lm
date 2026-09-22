from __future__ import annotations

import asyncio

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
