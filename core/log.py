"""Lightweight structured logging for LumaKit (R-6).

Broad exception handlers that keep the process alive must route through here
first so a degrading DB, model server, or callback is visible instead of
silently swallowed. Set LUMAKIT_LOG_LEVEL (DEBUG/INFO/WARNING/ERROR) to tune;
default WARNING.
"""

from __future__ import annotations

import logging
import os
import sys

_logger = logging.getLogger("lumakit")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s lumakit(%(component)s): %(message)s")
    )
    _logger.addHandler(_handler)
    _logger.setLevel(
        getattr(logging, str(os.getenv("LUMAKIT_LOG_LEVEL", "") or "WARNING").upper(), logging.WARNING)
    )
    _logger.propagate = False


def _log(level: int, component: str, message: str, exc: BaseException | None = None) -> None:
    if exc is not None:
        message = f"{message} ({type(exc).__name__}: {exc})"
    _logger.log(level, message, extra={"component": component})


def debug(component: str, message: str, exc: BaseException | None = None) -> None:
    _log(logging.DEBUG, component, message, exc)


def warn(component: str, message: str, exc: BaseException | None = None) -> None:
    _log(logging.WARNING, component, message, exc)


def error(component: str, message: str, exc: BaseException | None = None) -> None:
    _log(logging.ERROR, component, message, exc)
