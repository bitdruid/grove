"""
Cross-process Socket.IO emitter.

Web process: receives a real `SocketIO` server instance via `set_socketio()`.
Worker process: builds an external `SocketIO` client (message_queue mode) that
publishes to the same Redis pubsub backplane. Either way callers just use
`emit.msg(...)` / `emit.log_line(...)` regardless of which process they run in.
"""

from __future__ import annotations

import os

from grove.events import LOG_ROOM


class Emit:
    def __init__(self):
        self.socketio = None

    def set_socketio(self, socketio):
        self.socketio = socketio

    def init_app(self):
        """No-op kept for backwards compatibility with start.py."""
        pass

    def _ensure_external_client(self):
        """In worker processes, lazily build a SocketIO client bound to the redis backplane."""
        if self.socketio is not None:
            return
        mq = os.getenv("SOCKETIO_MESSAGE_QUEUE") or os.getenv("REDIS_URL")
        if not mq:
            return
        from flask_socketio import SocketIO
        self.socketio = SocketIO(message_queue=mq)

    def _emit(self, event: str, data, to: str | None = None, room: str | None = None):
        self._ensure_external_client()
        if self.socketio is None:
            return
        kwargs = {}
        if to:
            kwargs["to"] = to
        if room:
            kwargs["room"] = room
        self.socketio.emit(event, data, **kwargs)

    def log_line(self, line: dict):
        """Broadcast one structured log line to subscribers of the log room."""
        self._emit("log_line", line, room=LOG_ROOM)

    def msg(self, data: dict):
        self._emit("server_event", data)

    def job(self, job_id: str):
        """Emit ONE unified per-job snapshot (status + task progress + size + rows).

        Single channel for the jobs page: the client reloads on a structural
        change (status differs / job added or removed) and patches the live
        values (progress, size, rows) in place otherwise.
        """
        import json

        from grove.db import tbl_job

        row = tbl_job.query.filter_by(job_id=job_id).first()
        if not row:
            return
        self._emit("server_event", {"job": {
            "job_id": row.job_id,
            "status": row.job_status,
            "tasks": json.loads(row.job_tasks) if row.job_tasks else [],
            "bytes": row.job_bytes or 0,
            "rows": row.job_db_rows or 0,
        }})

    def refresh(self):
        self._emit("server_event", "refresh")

    def home(self):
        self._emit("server_event", "home")


emit = Emit()
