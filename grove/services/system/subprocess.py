"""
Thin subprocess helper. Spawns each child in its own process group so the
calling Celery task's SIGTERM handler (see grove.celery_app.FlaskTask) can
kill the whole tree with one syscall — no manual PID bookkeeping needed.
"""

from __future__ import annotations

import os
import signal
import subprocess


def spawn(args: list[str], **popen_kwargs) -> subprocess.Popen:
    """Popen wrapper that starts the child in a new session.

    `start_new_session=True` makes the child its own process-group leader, so
    descendants (e.g. wget's children) can be killed in one shot via killpg.
    """
    popen_kwargs.setdefault("stdout", subprocess.DEVNULL)
    popen_kwargs.setdefault("stderr", subprocess.DEVNULL)
    return subprocess.Popen(args, start_new_session=True, **popen_kwargs)


def kill_tree(proc: subprocess.Popen, sig: int = signal.SIGTERM) -> None:
    """Best-effort terminate of `proc` and all its descendants."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError):
        pass
