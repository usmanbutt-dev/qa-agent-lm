"""Bounded, redacted diagnostic and screenshot evidence."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import ConsoleMessage, Page, Request, Response

from qa_agent_lm.browser.errors import ArtifactLimitExceededError, InvalidRequestError

_REDACTED = "[REDACTED]"
_MASK_SCRIPT = """secrets => {
  const replacements = [];
  const redact = value => {
    let result = value;
    for (const secret of secrets) result = result.split(secret).join('[REDACTED]');
    return result;
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const redacted = redact(node.nodeValue || '');
    if (redacted !== node.nodeValue) {
      replacements.push({node, property: 'nodeValue', value: node.nodeValue});
      node.nodeValue = redacted;
    }
  }
  for (const element of document.querySelectorAll('input, textarea')) {
    const redacted = redact(element.value);
    if (redacted !== element.value) {
      replacements.push({node: element, property: 'value', value: element.value});
      element.value = redacted;
    }
  }
  for (const element of document.querySelectorAll('*')) {
    for (const attribute of element.attributes) {
      const redacted = redact(attribute.value);
      if (redacted !== attribute.value) {
        replacements.push({
          node: element, property: `attribute:${attribute.name}`, value: attribute.value
        });
        element.setAttribute(attribute.name, redacted);
      }
    }
  }
  window.__qaAgentRedactions = replacements;
}"""
_RESTORE_SCRIPT = """() => {
  for (const item of window.__qaAgentRedactions || []) {
    if (item.property.startsWith('attribute:')) {
      item.node.setAttribute(item.property.slice(10), item.value);
    } else {
      item.node[item.property] = item.value;
    }
  }
  delete window.__qaAgentRedactions;
}"""


@dataclass(frozen=True)
class DiagnosticEntry:
    evidence_id: str
    channel: str
    level: str
    message: str


@dataclass(frozen=True)
class DiagnosticsResult:
    entries: tuple[DiagnosticEntry, ...]
    truncated: bool


@dataclass(frozen=True)
class ScreenshotResult:
    artifact_id: str


@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_id: str
    kind: str
    label: str
    content_type: str
    filename: str
    size_bytes: int
    sha256: str
    redacted: bool


class EvidenceCollector:
    def __init__(
        self,
        page: Page,
        *,
        artifact_dir: Path,
        secret_values: tuple[str, ...],
        diagnostic_capacity: int,
        max_artifacts: int,
        max_screenshot_bytes: int,
    ) -> None:
        self._page = page
        self._artifact_dir = artifact_dir
        self._secret_values = tuple(
            sorted((value for value in secret_values if value), key=len, reverse=True)
        )
        self._entries: deque[DiagnosticEntry] = deque(maxlen=diagnostic_capacity)
        self._discarded_entries = 0
        self._evidence_counter = 0
        self._artifact_counter = 0
        self._max_artifacts = max_artifacts
        self._max_screenshot_bytes = max_screenshot_bytes

    def attach(self) -> None:
        self._page.on("console", self._on_console)
        self._page.on("requestfailed", self._on_request_failed)
        self._page.on("response", self._on_response)

    def read(self, channels: tuple[str, ...], max_entries: int) -> DiagnosticsResult:
        if not channels or not set(channels) <= {"console", "network"}:
            raise InvalidRequestError("channels must contain console, network, or both")
        if len(set(channels)) != len(channels):
            raise InvalidRequestError("channels must not contain duplicates")
        if not 1 <= max_entries <= 200:
            raise InvalidRequestError("max_entries must be between 1 and 200")
        matching = [entry for entry in self._entries if entry.channel in channels]
        selected = matching[-max_entries:]
        return DiagnosticsResult(
            entries=tuple(selected),
            truncated=self._discarded_entries > 0 or len(matching) > len(selected),
        )

    async def screenshot(self, label: str, *, full_page: bool, timeout_ms: int) -> ScreenshotResult:
        if self._artifact_counter >= self._max_artifacts:
            raise ArtifactLimitExceededError("Browser session exceeded its artifact limit")
        masked = False
        try:
            if self._secret_values:
                await self._page.evaluate(_MASK_SCRIPT, self._secret_values)
                masked = True
            image = await self._page.screenshot(full_page=full_page, timeout=timeout_ms)
        finally:
            if masked:
                await self._page.evaluate(_RESTORE_SCRIPT)
        if len(image) > self._max_screenshot_bytes:
            raise ArtifactLimitExceededError("Screenshot exceeded its byte limit")

        self._artifact_counter += 1
        artifact_id = f"artifact_{self._artifact_counter:06d}"
        filename = f"{artifact_id}.png"
        metadata = ArtifactMetadata(
            artifact_id=artifact_id,
            kind="screenshot",
            label=self._redact(label),
            content_type="image/png",
            filename=filename,
            size_bytes=len(image),
            sha256=hashlib.sha256(image).hexdigest(),
            redacted=bool(self._secret_values),
        )
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        (self._artifact_dir / filename).write_bytes(image)
        (self._artifact_dir / f"{artifact_id}.json").write_text(
            json.dumps(asdict(metadata), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return ScreenshotResult(artifact_id=artifact_id)

    def _append(self, channel: str, level: str, message: str) -> None:
        if len(self._entries) == self._entries.maxlen:
            self._discarded_entries += 1
        self._evidence_counter += 1
        self._entries.append(
            DiagnosticEntry(
                evidence_id=f"evidence_{self._evidence_counter:06d}",
                channel=channel,
                level=level,
                message=self._redact(message)[:4000],
            )
        )

    def _redact(self, value: str) -> str:
        for secret in self._secret_values:
            value = value.replace(secret, _REDACTED)
            value = value.replace(quote(secret, safe=""), _REDACTED)
        return value

    def _on_console(self, message: ConsoleMessage) -> None:
        levels = {"error": "error", "warning": "warning", "warn": "warning"}
        if message.type in levels:
            self._append("console", levels[message.type], message.text)

    def _on_request_failed(self, request: Request) -> None:
        failure = request.failure or "request failed"
        self._append("network", "error", f"{request.method} {request.url}: {failure}")

    def _on_response(self, response: Response) -> None:
        if response.status >= 400:
            self._append(
                "network",
                "error",
                f"{response.request.method} {response.url}: HTTP {response.status}",
            )
