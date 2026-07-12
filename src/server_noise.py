"""
Benign server-side noise filters.

Browsers can cancel in-flight page or asset requests while NiceGUI is still
building a response. On Windows this sometimes surfaces as a noisy
``ConnectionResetError`` or Starlette's ``RuntimeError("No response returned.")``.
These are client disconnects, not application failures.
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType


class _BenignDisconnectFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info is None:
            return True
        exc = record.exc_info[1]
        return not _is_benign_disconnect(exc)


def install_disconnect_noise_filters() -> None:
    """Suppress known client-disconnect tracebacks from uvicorn/asyncio logs."""
    disconnect_filter = _BenignDisconnectFilter()
    for logger_name in ("uvicorn.error", "asyncio"):
        logger = logging.getLogger(logger_name)
        if not any(isinstance(f, _BenignDisconnectFilter) for f in logger.filters):
            logger.addFilter(disconnect_filter)


def install_asyncio_disconnect_handler() -> None:
    """Ignore WinError 10054 raised from the event loop connection-lost callback."""
    loop = asyncio.get_running_loop()
    original_handler = loop.get_exception_handler()

    def _handle_exception(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if _is_connection_reset(exc):
            return
        if original_handler is not None:
            original_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(_handle_exception)


def _is_benign_disconnect(exc: BaseException | None) -> bool:
    if exc is None:
        return False
    if _is_connection_reset(exc):
        return True
    if isinstance(exc, RuntimeError) and str(exc) == "No response returned.":
        return _traceback_contains(exc.__traceback__, "starlette", "middleware", "base.py")
    if isinstance(exc, BaseExceptionGroup):
        return bool(exc.exceptions) and all(_is_benign_disconnect(child) for child in exc.exceptions)
    return False


def _is_connection_reset(exc: BaseException | None) -> bool:
    return isinstance(exc, ConnectionResetError) and getattr(exc, "winerror", None) == 10054


def _traceback_contains(traceback: TracebackType | None, *parts: str) -> bool:
    while traceback is not None:
        filename = traceback.tb_frame.f_code.co_filename.replace("\\", "/").lower()
        if all(part.lower() in filename for part in parts):
            return True
        traceback = traceback.tb_next
    return False
