"""
Celery application factory.

The Celery app is created at module import so workers can `celery -A grove.celery_app worker`
discover it without booting Flask first. `init_celery(flask_app)` then binds a Flask
application context onto every task so DB sessions, extensions and config work inside tasks.
"""

from __future__ import annotations

import os
import signal

import psutil
from celery import Celery, Task
from celery.signals import task_revoked, worker_process_init

from grove.extensions import logger


BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")


celery_app = Celery(
    "grove",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["grove.services.system.workflow.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,                # don't ack until finished — survives worker crashes
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,       # one job step per worker slot
    task_track_started=True,            # exposes STARTED state
    task_time_limit=60 * 60,            # hard kill after 1h
    task_soft_time_limit=55 * 60,
    broker_connection_retry_on_startup=True,
    result_extended=True,
)


class FlaskTask(Task):
    """
    Base Task that:
      • pushes a Flask app context around every run (so SQLAlchemy works),
      • installs a SIGTERM handler that kills the task's child-process tree
        before the worker exits — this is how `revoke(terminate=True)` cleans up
        wget / playwright / ocr subprocesses without leaking orphans.
    """

    abstract = True
    _flask_app = None  # set by init_celery()

    def __call__(self, *args, **kwargs):
        self._install_sigterm_handler()
        if self._flask_app is None:
            return self.run(*args, **kwargs)
        with self._flask_app.app_context():
            return self.run(*args, **kwargs)

    @staticmethod
    def _install_sigterm_handler():
        def _handler(signum, frame):
            try:
                me = psutil.Process(os.getpid())
                children = me.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                gone, alive = psutil.wait_procs(children, timeout=3)
                for child in alive:
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
            finally:
                raise SystemExit(0)

        signal.signal(signal.SIGTERM, _handler)


celery_app.Task = FlaskTask


def init_celery(flask_app):
    """Bind a Flask app onto the FlaskTask base. Call once from the web bootstrap
    AND from the worker bootstrap (worker.py imports the same flask app)."""
    FlaskTask._flask_app = flask_app
    flask_app.extensions["celery"] = celery_app
    return celery_app


@task_revoked.connect
def _on_revoked(sender=None, request=None, terminated=None, signum=None, expired=None, **_):
    logger.info(msg=f"Task revoked [{request.id if request else '?'}] terminated={terminated} signal={signum}")


@worker_process_init.connect
def _on_worker_init(**_):
    logger.info(msg=f"Celery worker process started [pid={os.getpid()}]")
