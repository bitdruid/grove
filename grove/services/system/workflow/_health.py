"""
Health/stats monitor for in-flight jobs.

Runs as a single Socket.IO background task inside the web process — which already
owns the Socket.IO server, DB and Flask app context — so it never competes with
the Celery worker pool. A multi-hour download holding the (single) worker slot
can no longer starve it, and stats stay live for every job step, not just ones
that report progress themselves.

Every HEALTH_INTERVAL_SECONDS it walks each active job's on-disk size + db row
count onto the job row (surfaced in the UI) and compares their sum to the last
reading: no growth flips the job to 'stuck' (self-healing back to 'process' once
growth resumes), growth emits an "alive" heartbeat log. `start_monitor(app)` is
called once from the web entrypoint; the worker never imports it.
"""

from __future__ import annotations

import os

from sqlalchemy import String, Text, func, select as sa_select

from grove.db import database, get_all_tables, tbl_job
from grove.extensions import logger, socketio
from grove.services.system.emit import emit

HEALTH_INTERVAL_SECONDS = 60

_ACTIVE_STATES = ("process", "stuck")


def _human(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f}{unit}"
        size /= 1024


def _count_db(job_id: str) -> int:
    total = 0
    for table in get_all_tables(exclude=["tbl_log"]):
        total += database.db.session.query(table).filter_by(job_id=job_id).count()
    return total


def _count_content(job_id: str) -> int:
    """Total bytes of text content across a job's rows — grows on UPDATEs too, so
    columns filled in place (exif/ocr/mail/whois) still register as progress."""
    total = 0
    for table in get_all_tables(exclude=["tbl_log"]):
        if "job_id" not in table.c:
            continue
        # LENGTH reads the stored length, not the blob, so this stays cheap
        text_cols = [c for c in table.c if c.name != "job_id" and isinstance(c.type, (String, Text))]
        if not text_cols:
            continue
        length_sum = sum(func.coalesce(func.length(c), 0) for c in text_cols)
        stmt = sa_select(func.coalesce(func.sum(length_sum), 0)).where(table.c.job_id == job_id)
        total += database.db.session.execute(stmt).scalar() or 0
    return total


def _count_size(job_path: str) -> int:
    total = 0
    if not os.path.isdir(job_path):
        return 0
    for dirpath, _, filenames in os.walk(job_path):
        for f in filenames:
            p = os.path.join(dirpath, f)
            if not os.path.islink(p):
                total += os.path.getsize(p)
    return total


def _write_stats(row) -> tuple[int, int]:
    """Persist a job's current on-disk size + db row count; return (size, db_rows)."""
    size = _count_size(row.job_path)
    db_rows = _count_db(row.job_id)
    row.job_bytes = size
    row.job_db_rows = db_rows
    database.db.session.commit()
    emit.job(row.job_id)
    return size, db_rows


def update_job_stats(job_id: str) -> None:
    """Recompute + store a single job's stats on demand (e.g. once it finishes)."""
    row = tbl_job.query.filter_by(job_id=job_id).first()
    if row:
        _write_stats(row)


def _tick(previous: dict[str, int]) -> dict[str, int]:
    """One monitoring pass over all active jobs; returns the new size+rows totals."""
    current: dict[str, int] = {}
    rows = tbl_job.query.filter(tbl_job.job_status.in_(_ACTIVE_STATES)).all()
    for row in rows:
        size, db_rows = _write_stats(row)
        # content bytes catch in-place UPDATEs that leave size+row count flat
        total = size + db_rows + _count_content(row.job_id)
        current[row.job_id] = total

        if total <= previous.get(row.job_id, 0):
            if row.job_status != "stuck":
                logger.warning(
                    msg=f"Job [{row.job_id}] does not respond - may regenerate",
                    extra={"job_id": row.job_id},
                )
                row.job_status = "stuck"
                database.db.session.commit()
        else:
            if row.job_status == "stuck":
                row.job_status = "process"
                database.db.session.commit()
            logger.info(
                msg=f"Job [{row.job_id}] alive — {_human(size)}, {db_rows} db rows",
                extra={"job_id": row.job_id},
            )
    return current


def start_monitor(app) -> None:
    """Launch the single background monitor loop. Call once from web startup."""

    def _loop():
        previous: dict[str, int] = {}
        while True:
            socketio.sleep(HEALTH_INTERVAL_SECONDS)
            try:
                with app.app_context():
                    previous = _tick(previous)
            except Exception as e:
                logger.error(msg=f"Health monitor error:\n{e}", exc_info=True)

    socketio.start_background_task(_loop)
    logger.info(msg="Health monitor started")
