"""
Background maintenance worker.

Runs as a single Socket.IO background task inside the web process (same pattern as
the health monitor) so it never competes with the Celery worker pool. It wakes every
MAINTENANCE_INTERVAL_SECONDS and runs each registered chore; chores gate their own
work (e.g. by staleness) so waking often is cheap. `start_maintenance(app)` is called
once from the web entrypoint; the worker never imports it.

Add future chores to _CHORES — each is a no-arg callable run inside an app context.
"""

from __future__ import annotations

import os
import time
import urllib.request

from grove.config import Config
from grove.extensions import logger, socketio
from grove.services.util import _valid_tlds

MAINTENANCE_INTERVAL_SECONDS = 6 * 60 * 60  # re-check chores every 6h

TLD_URL = "https://data.iana.org/TLD/tlds-alpha-by-domain.txt"
TLD_MAX_AGE_DAYS = 30


def _tld_age_days() -> float:
    """Age of the bundled TLD file in days (inf if missing)."""
    try:
        return (time.time() - os.path.getmtime(Config.TLDS)) / 86400
    except OSError:
        return float("inf")


def _refresh_tlds() -> None:
    """Refresh the IANA TLD list if the local copy is stale; keep the snapshot on failure."""
    if _tld_age_days() < TLD_MAX_AGE_DAYS:
        return
    try:
        with urllib.request.urlopen(TLD_URL, timeout=30) as resp:
            data = resp.read().decode("utf-8")
        if len(data.splitlines()) < 100:  # sanity-guard against error pages / truncation
            raise ValueError("TLD payload too short")
        tmp = f"{Config.TLDS}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, Config.TLDS)  # atomic swap so a reader never sees a half-file
        _valid_tlds.cache_clear()     # drop the cached set so the next lookup reloads
        logger.info(msg=f"TLD list refreshed from IANA ({len(data.splitlines())} lines)")
    except Exception as e:
        logger.warning(msg=f"TLD refresh failed, keeping bundled snapshot: {e}")


_CHORES = [_refresh_tlds]


def start_maintenance(app) -> None:
    """Launch the single maintenance loop. Call once from web startup."""

    def _loop():
        while True:
            for chore in _CHORES:
                try:
                    with app.app_context():
                        chore()
                except Exception as e:
                    logger.error(msg=f"Maintenance chore {chore.__name__} failed:\n{e}", exc_info=True)
            socketio.sleep(MAINTENANCE_INTERVAL_SECONDS)

    socketio.start_background_task(_loop)
    logger.info(msg="Maintenance worker started")
