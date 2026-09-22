"""Typed failures exposed by the restricted browser runtime."""


class BrowserSessionError(RuntimeError):
    """Base class for browser-session failures."""

    code = "TOOL_EXECUTION_FAILED"
    retryable = False


class SessionClosedError(BrowserSessionError):
    code = "SESSION_CLOSED"


class OriginNotAllowedError(BrowserSessionError):
    code = "ORIGIN_NOT_ALLOWED"


class ExternalProtocolBlockedError(BrowserSessionError):
    code = "EXTERNAL_PROTOCOL_BLOCKED"


class DownloadBlockedError(BrowserSessionError):
    code = "DOWNLOAD_BLOCKED"


class NavigationTimeoutError(BrowserSessionError):
    code = "NAVIGATION_TIMEOUT"
    retryable = True


class ActionTimeoutError(BrowserSessionError):
    code = "ACTION_TIMEOUT"
    retryable = True


class TargetNotFoundError(BrowserSessionError):
    code = "TARGET_NOT_FOUND"
    retryable = True


class StaleElementReferenceError(BrowserSessionError):
    code = "STALE_ELEMENT_REFERENCE"
    retryable = True


class InvalidRequestError(BrowserSessionError):
    code = "INVALID_REQUEST"


class StepLimitExceededError(BrowserSessionError):
    code = "STEP_LIMIT_EXCEEDED"


class WallClockTimeoutError(BrowserSessionError):
    code = "WALL_CLOCK_TIMEOUT"
