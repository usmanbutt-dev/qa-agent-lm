from __future__ import annotations

import pytest

from qa_agent_lm.browser.errors import (
    ExternalProtocolBlockedError,
    InvalidRequestError,
    StaleElementReferenceError,
    TargetNotFoundError,
)
from qa_agent_lm.browser.session import BrowserSession, BrowserSessionConfig

pytestmark = pytest.mark.asyncio


async def test_complete_form_interaction(origins: tuple[str, str]) -> None:
    allowed, _ = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        await session.navigate(f"{allowed}/form")
        observation = await session.inspect()

        assert observation.url == f"{allowed}/form"
        assert observation.truncated is False
        assert len(observation.elements) == 3
        name = next(element for element in observation.elements if element.name == "Name")
        notes = next(element for element in observation.elements if element.name == "Notes")
        submit = next(element for element in observation.elements if element.name == "Save profile")

        replaced = await session.type(name.element_ref, "Usman")
        appended = await session.type(notes.element_ref, "QA", replace=False)
        clicked = await session.click(submit.element_ref)

        assert replaced.characters_written == 5
        assert appended.characters_written == 2
        assert clicked.navigation_occurred is False
        final_observation = await session.inspect()
        assert any(element.name == "Saved Usman|QA" for element in final_observation.elements)


async def test_observation_is_bounded_and_reports_truncation(
    origins: tuple[str, str],
) -> None:
    allowed, _ = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        await session.navigate(f"{allowed}/form")
        observation = await session.inspect(max_elements=2)

        assert len(observation.elements) == 2
        assert observation.truncated is True


async def test_element_references_expire_after_next_observation(
    origins: tuple[str, str],
) -> None:
    allowed, _ = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        await session.navigate(f"{allowed}/form")
        first = await session.inspect()
        await session.inspect()

        with pytest.raises(StaleElementReferenceError):
            await session.click(first.elements[0].element_ref)


async def test_unknown_current_element_reference_is_rejected(
    origins: tuple[str, str],
) -> None:
    allowed, _ = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        await session.navigate(f"{allowed}/form")
        observation = await session.inspect()
        generation = observation.observation_id.removeprefix("obs_")

        with pytest.raises(TargetNotFoundError):
            await session.click(f"el_{generation}_9999")


@pytest.mark.parametrize("max_elements", [0, 201])
async def test_inspect_rejects_invalid_bounds(origins: tuple[str, str], max_elements: int) -> None:
    allowed, _ = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        await session.navigate(f"{allowed}/form")
        with pytest.raises(InvalidRequestError):
            await session.inspect(max_elements=max_elements)


async def test_type_rejects_invalid_text(origins: tuple[str, str]) -> None:
    allowed, _ = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        await session.navigate(f"{allowed}/form")
        observation = await session.inspect()
        target = observation.elements[0]

        with pytest.raises(InvalidRequestError):
            await session.type(target.element_ref, "")


async def test_click_rejects_external_protocol_before_activation(
    origins: tuple[str, str],
) -> None:
    allowed, _ = origins
    async with BrowserSession(BrowserSessionConfig(allowed_origins=(allowed,))) as session:
        await session.navigate(f"{allowed}/unsafe")
        observation = await session.inspect()

        with pytest.raises(ExternalProtocolBlockedError):
            await session.click(observation.elements[0].element_ref)
