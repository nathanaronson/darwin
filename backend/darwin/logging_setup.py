"""Central logging config.

Called once at process start from the FastAPI lifespan hook and from
the CLI entrypoint. Writes to stdout with a tight format so every line
shows up cleanly under `honcho` prefixed as `backend.1 | ...`.

Set ``LOG_LEVEL`` in `.env` (or the shell) to ``DEBUG`` / ``INFO`` /
``WARNING``. Default is ``INFO``.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def setup_logging() -> None:
    """Idempotent root-logger configuration."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet down the noisy libraries unless DEBUG was explicitly requested.
    if level != "DEBUG":
        for noisy in ("httpx", "httpcore", "urllib3", "watchfiles"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    logging.getLogger("darwin").info("logging configured at level=%s", level)
