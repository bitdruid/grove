import logging
import logging.handlers
import os
from datetime import datetime

from flask import Flask

from grove.db import database
from grove.db import tbl_log

from grove.services.system.emit import emit


class SQLiteHandler(logging.Handler):
    def __init__(self, flask: Flask):
        super().__init__()
        self.flask = flask

    def emit(self, record):
        with self.flask.app_context():
            database.db.session.add(
                tbl_log(
                    log_date=datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                    log_level=record.levelname,
                    log_module=record.module,
                    log_func=record.funcName,
                    log_job_id=getattr(record, "job_id", None),
                    log_msg=record.msg,
                )
            )
            database.db.session.commit()


class SocketioHandler(logging.Handler):
    def __init__(self, flask: Flask):
        super().__init__()

    def emit(self, record):
        try:
            emit.log_line(
                {
                    "ts": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                    "level": record.levelname,
                    "module": record.module,
                    "func": record.funcName,
                    "msg": record.getMessage(),
                }
            )
        except Exception:
            pass


class Log:
    @property
    def debug(self):
        return self.log.debug

    @property
    def info(self):
        return self.log.info

    @property
    def warning(self):
        return self.log.warning

    @property
    def error(self):
        return self.log.error

    def __init__(self):
        self.log = logging.getLogger("grove")
        self.log.setLevel(logging.DEBUG)

    def init_app(self, flask: Flask):
        with flask.app_context():
            logfile = os.path.join(flask.instance_path, "grove.log")

            if not self.log.hasHandlers():
                formatter = logging.Formatter(
                    "[%(asctime)s] %(levelname)s in %(module)s.%(funcName)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
                )

                console_handler = logging.StreamHandler()
                console_handler.setFormatter(formatter)

                rotation_handler = logging.handlers.RotatingFileHandler(
                    logfile, maxBytes=5 * 1024 * 1024, backupCount=1
                )
                rotation_handler.setFormatter(formatter)

                db_handler = SQLiteHandler(flask)

                emit_handler = SocketioHandler(flask)
                emit_handler.setFormatter(formatter)

                self.log.addHandler(console_handler)
                self.log.addHandler(rotation_handler)
                self.log.addHandler(db_handler)
                self.log.addHandler(emit_handler)

                # stop root logger hijacked by celery worker and double each line in `docker logs`
                self.log.propagate = False

        return self.log
