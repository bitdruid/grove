"""
Celery task pipeline.

Each tool runs as its own task. They are glued together with `chain(...)` so
the result of a step is just the job_id passed downstream — there's no shared
mutable state across tasks. Cancellation is `AsyncResult.revoke(terminate=True)`
on the chain's task id; the FlaskTask base handles tearing down subprocesses.
"""

from __future__ import annotations

import os

from celery import chain

from grove.celery_app import celery_app

# Downloads may run for hours, past the global 55m/60m cap; give them a generous env-tunable limit (wget --timeout/--tries guard runaways).
_DOWNLOAD_SOFT_LIMIT = int(os.getenv("GROVE_DOWNLOAD_SOFT_LIMIT", str(24 * 60 * 60)))
_DOWNLOAD_HARD_LIMIT = int(os.getenv("GROVE_DOWNLOAD_HARD_LIMIT", str(24 * 60 * 60 + 300)))
from grove.extensions import logger
from grove.services.system.emit import emit
from grove.services.system.search import search_index
from grove.services.system.workflow._health import update_job_stats
from grove.services.system.workflow._job import _Job
from grove.services.tools.arecord import arecord
from grove.services.tools.code import analyzer, downloader
from grove.services.tools.geoip import geoip
from grove.services.tools.lookup import lookup
from grove.services.tools.offline_result import offline_result
from grove.services.tools.screenshot import screenshot
from grove.services.tools.subdomain import subdomain
from grove.services.util import zip_path


# helpers

def _load(job_id: str) -> _Job:
    job = _Job()
    job._get_existing(job_id)
    return job


def _mark(job: _Job, task: str, status: str = "done") -> None:
    job._set_task_status(task, status)


# lifecycle tasks

@celery_app.task(name="job.start")
def task_start(job_id: str) -> str:
    job = _load(job_id)
    job._set_status("process")
    logger.info(msg=f"Processing job [{job_id}]")
    return job_id


@celery_app.task(name="job.finish")
def task_finish(job_id: str) -> str:
    job = _load(job_id)
    job._set_status("prepare")
    job._set_date_end()
    analyzer.resolve_hlink_locals(job_id, job.job_path)
    offline_result.request(job_id, job_path=job.job_path)
    zip_path(job.job_path)
    update_job_stats(job_id)  # final reading — monitor only ticks 'process'/'stuck', not 'prepare'
    job._set_status("done")
    logger.info(msg=f"Finished job [{job_id}]")
    return job_id


# pipeline tasks (one per tool)


@celery_app.task(name="job.lookup")
def task_lookup(job_id: str) -> str:
    job = _load(job_id)
    lookup.request(job_id)
    _mark(job, "lookup")
    return job_id


@celery_app.task(name="job.arecord")
def task_arecord(job_id: str) -> str:
    job = _load(job_id)
    arecord.request(job_id)
    _mark(job, "arecord")
    return job_id


@celery_app.task(name="job.geoip")
def task_geoip(job_id: str) -> str:
    job = _load(job_id)
    geoip.request(job_id)
    _mark(job, "geoip")
    return job_id


@celery_app.task(name="job.subdomain")
def task_subdomain(job_id: str) -> str:
    job = _load(job_id)
    subdomain.request(job_id)
    _mark(job, "subdomain")
    return job_id


@celery_app.task(name="job.source_index", soft_time_limit=_DOWNLOAD_SOFT_LIMIT, time_limit=_DOWNLOAD_HARD_LIMIT)
def task_source_index(job_id: str) -> str:
    job = _load(job_id)
    downloader.source_index(job_id=job_id, job_path=job.job_path)
    _mark(job, "source_index")
    return job_id


@celery_app.task(name="job.source_full", soft_time_limit=_DOWNLOAD_SOFT_LIMIT, time_limit=_DOWNLOAD_HARD_LIMIT)
def task_source_full(job_id: str) -> str:
    job = _load(job_id)
    downloader.source_full(job_id=job_id, job_path=job.job_path)
    _mark(job, "source_full")
    return job_id


@celery_app.task(name="job.archive_latest", soft_time_limit=_DOWNLOAD_SOFT_LIMIT, time_limit=_DOWNLOAD_HARD_LIMIT)
def task_archive_latest(job_id: str) -> str:
    job = _load(job_id)
    downloader.archive_latest(job_id, job.job_path)
    _mark(job, "archive_latest")
    return job_id


@celery_app.task(name="job.archive_2y", soft_time_limit=_DOWNLOAD_SOFT_LIMIT, time_limit=_DOWNLOAD_HARD_LIMIT)
def task_archive_2y(job_id: str) -> str:
    job = _load(job_id)
    downloader.archive_2y(job_id, job.job_path)
    _mark(job, "archive_2y")
    return job_id


@celery_app.task(name="job.screenshot")
def task_screenshot(job_id: str) -> str:
    job = _load(job_id)
    mode = "full" if job.job_config.screenshot_full else "index"
    screenshot.request(job_id, job_input=job.job_input, job_path=job.job_path, mode=mode)
    _mark(job, "screenshot")
    return job_id


@celery_app.task(name="job.img_ocr")
def task_img_ocr(job_id: str) -> str:
    job = _load(job_id)
    analyzer.get_img_ocr(job_id=job_id)
    _mark(job, "img_ocr")
    return job_id


@celery_app.task(name="job.pdf_ocr")
def task_pdf_ocr(job_id: str) -> str:
    job = _load(job_id)
    analyzer.get_pdf_ocr(job_id=job_id)
    _mark(job, "pdf_ocr")
    return job_id


@celery_app.task(name="job.exif")
def task_exif(job_id: str) -> str:
    job = _load(job_id)
    analyzer.get_exif(job_id=job_id)
    _mark(job, "exif")
    return job_id


@celery_app.task(name="job.mail")
def task_mail(job_id: str) -> str:
    job = _load(job_id)
    analyzer.get_content_mail(job_id=job_id)
    _mark(job, "mail")
    return job_id


@celery_app.task(name="job.search_index")
def task_search_index(job_id: str) -> str:
    job = _load(job_id)
    search_index.request(job_id)
    _mark(job, "search_index")
    return job_id


# chain builder

def build_pipeline(job: _Job):
    """Build the Celery chain for a job. Mirrors the old _Task._process_job order."""
    steps = ["lookup", "arecord", "geoip"]
    if job.job_config.subdomain:
        steps.append("subdomain")
    if job.job_config.source_index or job.job_config.source_full:
        steps.append("source_index")
    if job.job_config.source_full:
        steps.append("source_full")
    if job.job_config.archive_latest:
        steps.append("archive_latest")
    if job.job_config.archive_2y:
        steps.append("archive_2y")
    if job.job_config.screenshot_index or job.job_config.screenshot_full:
        steps.append("screenshot")
    steps.extend(["img_ocr", "pdf_ocr", "exif", "mail", "search_index"])
    job._init_tasks(steps)

    sig_map = {
        "lookup": task_lookup,
        "arecord": task_arecord,
        "geoip": task_geoip,
        "subdomain": task_subdomain,
        "source_index": task_source_index,
        "source_full": task_source_full,
        "archive_latest": task_archive_latest,
        "archive_2y": task_archive_2y,
        "screenshot": task_screenshot,
        "img_ocr": task_img_ocr,
        "pdf_ocr": task_pdf_ocr,
        "exif": task_exif,
        "mail": task_mail,
        "search_index": task_search_index,
    }

    signatures = [task_start.s(job.job_id)]
    signatures.extend(sig_map[name].s() for name in steps)
    signatures.append(task_finish.s())
    return chain(*signatures)
