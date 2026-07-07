from flask import request
from flask_socketio import join_room, leave_room

from grove.db import database, tbl_log

LOG_ROOM = "log_stream"


def _format_row(row) -> dict:
    return {
        "ts": row.log_date,
        "level": row.log_level,
        "module": row.log_module,
        "func": row.log_func,
        "msg": row.log_msg,
    }


def request_log(socketio):
    """Send the recent log history to the requesting client only."""
    rows = database.db.session.query(tbl_log).order_by(tbl_log.id.desc()).limit(1000).all()
    rows.reverse()
    socketio.emit(
        "log_history",
        {"lines": [_format_row(r) for r in rows]},
        to=request.sid,
    )


def subscribe_log():
    """Join the log-stream room so this client receives live lines."""
    join_room(LOG_ROOM)


def unsubscribe_log():
    leave_room(LOG_ROOM)
