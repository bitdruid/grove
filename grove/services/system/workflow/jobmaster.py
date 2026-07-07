"""
JobMaster — public facade for job lifecycle.

Same API as before (create_job, fetch_job, del_job, get_job_status, …) but the
processing loop is gone: when a job is created we dispatch a Celery chain and
store its root task id. Cancellation = `AsyncResult(task_id).revoke(terminate=True)`.
"""

from __future__ import annotations

import os
import shutil

from celery.result import AsyncResult
from flask import Flask

from grove.celery_app import celery_app, init_celery
from grove.db import database, get_all_tables, select, tbl_job
from grove.extensions import logger
from grove.services.system.workflow._job import _Job


class JobMaster:
    def __init__(self):
        self.flask: Flask | None = None

    def init_app(self, flask: Flask):
        self.flask = flask
        init_celery(flask)

    # job creation / dispatch

    def create_job(self, job_type: str, job_input: str, job_config: dict | None = None) -> bool:
        job = _Job()
        if not job._create(job_type=job_type, job_input=job_input, job_config=job_config):
            return False
        self._dispatch(job)
        return True

    def _dispatch(self, job: _Job):
        """Build and submit the Celery chain for a job, persisting its task id."""
        from grove.services.system.workflow.tasks import build_pipeline

        os.makedirs(job.job_path, exist_ok=True)
        pipeline = build_pipeline(job)
        result = pipeline.apply_async()
        job._set_task_id(result.id)
        logger.info(msg=f"Dispatched chain [{result.id}] for job [{job.job_id}]")

    # job lookup

    def fetch_job(self, job_id: str | None = None) -> _Job | None:
        if not job_id:
            return None
        job = _Job()
        job._get_existing(job_id)
        return job if job.job_id else None

    def get_job_status(self, job_id: str) -> str | bool:
        row = tbl_job.query.filter_by(job_id=job_id).first()
        return row.job_status if row else False

    def get_job_input(self, job_id: str):
        return tbl_job.query.with_entities(tbl_job.job_id).filter_by(job_id=job_id).first()

    def count_jobs(self, with_id: bool = False):
        if with_id:
            return database.db.session.execute(select(tbl_job.job_id)).scalars().all()
        return tbl_job.query.count()

    # job control

    def kill(self, job_id: str) -> None:
        """Revoke the running chain for a job. Worker's SIGTERM handler kills subprocesses."""
        row = tbl_job.query.filter_by(job_id=job_id).first()
        if not row or not row.job_task_id:
            return
        AsyncResult(row.job_task_id, app=celery_app).revoke(terminate=True, signal="SIGTERM")
        logger.info(msg=f"Revoked task [{row.job_task_id}] for job [{job_id}]")

    def del_job(self, job_id: str) -> bool:
        try:
            self.kill(job_id)
            forbidden_tables = ["tbl_log"]
            job = self.fetch_job(job_id)
            if not job:
                return False
            for table in get_all_tables(exclude=forbidden_tables):
                database.db.session.execute(table.delete().where(table.c.job_id == job.job_id))
            database.db.session.commit()
            from grove.services.system.search import drop_job

            drop_job(job.job_id)
            self.clean_jobdir()
            logger.info(msg=f"Job [{job_id}] has been deleted.", extra={"job_id": job_id})
            return True
        except Exception as e:
            logger.error(msg=f"Error deleting job:\n{e}", extra={"job_id": job_id}, exc_info=True)
            database.db.session.rollback()
            return False

    # filesystem

    def clean_jobdir(self):
        path = os.path.join(os.getcwd(), "jobs")
        if not os.path.isdir(path):
            return
        active = set(self.count_jobs(with_id=True))
        for jobdir in os.listdir(path):
            full = os.path.join(path, jobdir)
            if not os.path.isdir(full):
                continue
            if jobdir not in active:
                shutil.rmtree(full)
                logger.debug(msg=f"Orphane jobdir removed [{jobdir}]")

    def job_zip(self, job_id: str) -> str | None:
        job = self.fetch_job(job_id)
        if not job or self.get_job_status(job_id) != "done":
            return None
        zip_path = os.path.abspath(os.path.join(job.job_path, f"{job.job_id}.zip"))
        return zip_path if os.path.isfile(zip_path) else None

    # data extraction

    def get_all_job_data(self, job_id: str, only_completed: bool = False) -> dict | None:
        forbidden_status = ["new", "process"]
        forbidden_tables = ["tbl_job", "tbl_log"]
        job = self.fetch_job(job_id)
        if not job:
            return None
        if only_completed and self.get_job_status(job_id) in forbidden_status:
            return None
        job_data: dict = {}
        for table in get_all_tables(exclude=forbidden_tables):
            if "job_id" not in table.columns:
                continue
            rows = database.db.session.query(table).filter(table.c.job_id == job_id).all()
            job_data[table.name] = [{col.name: getattr(row, col.name) for col in table.columns} for row in rows]
        return job_data

    # status setters (kept for callers/templates)

    def _set(self, job_id: str, status: str):
        job = self.fetch_job(job_id)
        if job:
            job._set_status(status)

    def set_job_status_new(self, job_id: str):
        self._set(job_id, "new")

    def set_job_status_process(self, job_id: str):
        self._set(job_id, "process")

    def set_job_status_prepare(self, job_id: str):
        self._set(job_id, "prepare")

    def set_job_status_done(self, job_id: str):
        self._set(job_id, "done")

    def set_job_status_stuck(self, job_id: str):
        self._set(job_id, "stuck")

    def set_job_status_fail(self, job_id: str):
        self._set(job_id, "fail")


jm = JobMaster()
