from __future__ import annotations
import typing

import json
from datetime import datetime

from grove.db import database, insert, tbl_job, tbl_hlink

from grove.extensions import logger
from grove.services.system.emit import emit
from grove.services.validation import get_primary

if typing.TYPE_CHECKING:
    from grove.services.system.workflow.jobmaster import JobMaster


class JobConfig:
    """
    Parses and stores boolean job configuration options based on the provided dictionary.
    """

    def __init__(self, job_config: dict):
        self.raw = job_config
        self.source_index = False
        self.source_full = False
        self.archive_latest = False
        self.archive_all = False
        self.archive_start = None
        self.archive_end = None
        self.screenshot_index = False
        self.screenshot_full = False
        self.subdomain = False
        self.parse_dict()

    def parse_dict(self) -> None:
        source = self.raw.get("task_source")
        self.source_index = source == "index"
        self.source_full = source == "full"

        archive = self.raw.get("task_archive")
        self.archive_latest = archive == "latest"
        self.archive_all = archive == "all"
        self.archive_start = self.raw.get("task_archive_start") or None
        self.archive_end = self.raw.get("task_archive_end") or None

        screenshot = self.raw.get("task_screenshot")
        self.screenshot_index = screenshot == "index"
        self.screenshot_full = screenshot == "full"

        self.subdomain = self.raw.get("task_subdomain") == "on"


class _Job:
    def __init__(self):
        """Create a new job. Assigns existing job if job_id is given."""
        self.job_id = None
        self.job_date_start = None
        self.job_date_end = None
        self.job_type = None
        self.job_input = None
        self.job_domain = None
        self.job_ipv4 = None
        self.job_path = None
        self.job_config = None
        self.job_tasks = []

    def _create(self, job_type: str, job_input: str, job_config: dict = None) -> bool:
        """Create a new job. Returns bool for success/fail."""
        try:
            new_job = tbl_job(
                job_id=f"{job_input}",
                job_date_start=datetime.now().strftime("%Y-%m-%d - %H:%M:%S"),
                job_date_end=None,
                job_type=job_type,
                job_input=job_input,
                job_domain=None,
                job_ipv4=None,
                job_path=f"jobs/{job_input}",
                job_status="new",
                job_config=json.dumps(job_config),
            )
            database.db.session.add(new_job)
            database.db.session.flush()
            new_job.job_id = f"{new_job.job_id}_{new_job.id}"
            new_job.job_path = f"{new_job.job_path}_{new_job.id}"
            new_job.job_domain, new_job.job_ipv4 = get_primary(new_job.job_input)
            database.db.session.commit()
            logger.info(msg="\nNEW JOB\nNEW JOB")
            logger.info(msg=f"Job [{new_job.job_id}] has been created.", extra={"job_id": new_job.job_id})

            hyperlinks = job_config.get("task_hyperlink", None)
            if hyperlinks:
                database.db.session.add_all(
                    [
                        tbl_hlink(
                            job_id=new_job.job_id,
                            c_hlink_link=link,
                        )
                        for link in hyperlinks
                        if link.strip()
                    ]
                )
            database.db.session.commit()

            self._get_existing(new_job.job_id)
            return True
        except Exception as e:
            logger.info(msg=f"Job [{new_job.job_id}] could not be created:\n{e}.", extra={"job_id": new_job.job_id})
            return False

    def _get_pending(self):
        """Get the next unprocessed job from the db."""
        job = database.db.session.execute(database.db.select(tbl_job).filter_by(job_status="new")).scalar()
        if job:
            self.job_id = job.job_id
            self.job_date_start = job.job_date_start
            self.job_date_end = job.job_date_end
            self.job_type = job.job_type
            self.job_input = job.job_input
            self.job_domain = job.job_domain
            self.job_ipv4 = job.job_ipv4
            self.job_path = job.job_path
            self.job_config = JobConfig(json.loads(job.job_config))
            self._load_tasks(job.job_tasks)

    def _get_existing(self, job_id: str):
        """Load a specific job from the db."""
        job = tbl_job.query.filter_by(job_id=job_id).first()
        if job:
            self.job_id = job.job_id
            self.job_date_start = job.job_date_start
            self.job_date_end = job.job_date_end
            self.job_type = job.job_type
            self.job_input = job.job_input
            self.job_domain = job.job_domain
            self.job_ipv4 = job.job_ipv4
            self.job_path = job.job_path
            self.job_config = JobConfig(json.loads(job.job_config))
            self._load_tasks(job.job_tasks)

    def _init_tasks(self, task_names: list[str]):
        """Initialize the task list for this job and persist to DB."""
        self.job_tasks = [{"task": name, "status": "new"} for name in task_names]
        self._save_tasks()

    def _set_task_status(self, task_name: str, status: str):
        """Update a specific task's status and persist to DB."""
        for task in self.job_tasks:
            if task["task"] == task_name:
                task["status"] = status
                break
        self._save_tasks()
        emit.job(self.job_id)
        logger.debug(msg=f"Task [{task_name}] set to '{status}'.", extra={"job_id": self.job_id})

    def _save_tasks(self):
        """Persist current task list to DB."""
        database.db.session.execute(
            database.db.update(tbl_job).where(tbl_job.job_id == self.job_id).values(job_tasks=json.dumps(self.job_tasks))
        )
        database.db.session.commit()

    def _load_tasks(self, raw: str):
        """Load tasks from DB JSON string."""
        if raw:
            self.job_tasks = json.loads(raw)
        else:
            self.job_tasks = []

    def _set_status(self, status: str):
        """Set own status"""
        database.db.session.execute(
            database.db.update(tbl_job).where(tbl_job.job_id == self.job_id).values(job_status=status)
        )
        database.db.session.commit()
        emit.job(self.job_id)
        logger.debug(
            msg=f"Job [{self.job_id}] status set to '{status}'.",
            extra={"job_id": self.job_id},
        )

    def _set_task_id(self, task_id: str):
        """Persist the Celery chain root task id (used by JobMaster.kill)."""
        database.db.session.execute(
            database.db.update(tbl_job).where(tbl_job.job_id == self.job_id).values(job_task_id=task_id)
        )
        database.db.session.commit()

    def _set_date_end(self):
        """Set jobs end-date"""
        database.db.session.execute(
            database.db.update(tbl_job)
            .where(tbl_job.job_id == self.job_id)
            .values(job_date_end=datetime.now().strftime("%Y-%m-%d - %H:%M:%S"))
        )
        database.db.session.commit()
        logger.debug(
            msg=f"Job [{self.job_id}] end-date set.",
            extra={"job_id": self.job_id},
        )
