from __future__ import annotations

import json
from pathlib import Path

import pytest

from qa_agent_lm.browser.errors import ArtifactLimitExceededError
from qa_agent_lm.browser.session import BrowserSession, BrowserSessionConfig

pytestmark = pytest.mark.asyncio


async def test_diagnostics_are_bounded_and_redacted(
    origins: tuple[str, str], tmp_path: Path
) -> None:
    allowed, _ = origins
    config = BrowserSessionConfig(
        allowed_origins=(allowed,),
        artifact_dir=tmp_path,
        secret_values=("super-secret",),
        diagnostic_capacity=2,
    )
    async with BrowserSession(config) as session:
        await session.navigate(f"{allowed}/diagnostics")
        result = await session.read_diagnostics(("console", "network"), max_entries=2)
        bounded = await session.read_diagnostics(("console", "network"), max_entries=1)

    assert len(result.entries) == 2
    assert len(bounded.entries) == 1
    assert bounded.truncated is True
    assert result.truncated is True
    assert all("super-secret" not in entry.message for entry in result.entries)
    assert any("[REDACTED]" in entry.message for entry in result.entries)


async def test_screenshot_has_deterministic_metadata_and_restores_page(
    origins: tuple[str, str], tmp_path: Path
) -> None:
    allowed, _ = origins
    config = BrowserSessionConfig(
        allowed_origins=(allowed,),
        artifact_dir=tmp_path,
        secret_values=("super-secret",),
    )
    async with BrowserSession(config) as session:
        await session.navigate(f"{allowed}/diagnostics")
        result = await session.take_screenshot("diagnostic super-secret")
        observation = await session.inspect()

    assert result.artifact_id == "artifact_000001"
    image_path = tmp_path / "artifact_000001.png"
    metadata_path = tmp_path / "artifact_000001.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert image_path.is_file()
    assert metadata["artifact_id"] == result.artifact_id
    assert metadata["filename"] == image_path.name
    assert metadata["size_bytes"] == image_path.stat().st_size
    assert metadata["redacted"] is True
    assert metadata["label"] == "diagnostic [REDACTED]"
    assert "super-secret" not in metadata_path.read_text(encoding="utf-8")
    assert any(element.name == "super-secret" for element in observation.elements)


async def test_artifact_limit_fails_before_second_persistence(
    origins: tuple[str, str], tmp_path: Path
) -> None:
    allowed, _ = origins
    config = BrowserSessionConfig(
        allowed_origins=(allowed,), artifact_dir=tmp_path, max_artifacts=1
    )
    async with BrowserSession(config) as session:
        await session.navigate(f"{allowed}/ok")
        await session.take_screenshot("first")
        with pytest.raises(ArtifactLimitExceededError):
            await session.take_screenshot("second")

    assert len(list(tmp_path.glob("*.png"))) == 1
