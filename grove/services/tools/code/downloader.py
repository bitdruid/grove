from __future__ import annotations

from celery.exceptions import SoftTimeLimitExceeded
from pywaybackup import PyWayBackup

from grove.db import database, select, tbl_hlink, tbl_job
from grove.extensions import logger
from grove.services.system.subprocess import spawn, kill_tree
from grove.services.tools.code.analyzer import analyze_code


def __source(mode: str, job_id, url_list: list, source_path: str):
    proc = None
    try:
        for url in url_list:
            depth = "1" if "index" in mode else "10"  # wget treats -l 0 as *infinite* depth, so index must be 1
            proc = spawn(
                [
                    "wget",
                    "--quiet",
                    "--execute=robots=off",
                    "--tries=1",
                    "--timeout=5",
                    "--connect-timeout=5",
                    "-P",
                    source_path,
                    "-c",
                    "-r",
                    "-k",
                    "-l",
                    depth,
                    "--no-check-certificate",
                    url,
                ]
            )
            logger.debug(msg=f"Spawned wget process with URL [{url}]", extra={"job_id": job_id})
            proc.wait()
            logger.info(msg=f"Downloaded source code from URL [{url}]", extra={"job_id": job_id})
        # Analyze once after all URLs are fetched
        if url_list:
            analyze_code(job_id, url_list[0], source_path, url_list[0], "source")
    except SoftTimeLimitExceeded:
        # Kill wget's tree — spawned in its own session, it would otherwise outlive the task.
        if proc is not None:
            kill_tree(proc)
        logger.warning(msg="Source download hit the task time limit; wget stopped", extra={"job_id": job_id})
        raise
    except Exception as e:
        logger.error(msg=f"Error downloading source:\n{e}", extra={"job_id": job_id}, exc_info=True)


def __archive(mode, job_id, url_list: list, archive_path: str, meta_path: str) -> bool:
    try:
        if not url_list:
            return True
        # One call on the domain: pywaybackup matches by URL prefix (no explicit=), so
        # domain/* — every subpage/subdomain — is covered. Looping the hlinks would just
        # re-fetch subsets and spawn multiple PyWayBackup instances (in-process index clash).
        domain = url_list[0]
        backup = None
        # output = downloaded site content; metadata = pywaybackup's own csv/db/cdx bookkeeping.
        # silent + no progress: the tqdm bars are noise in a non-TTY worker and get doubled by celery stdout/stderr
        if "latest" in mode:
            backup = PyWayBackup(
                url=domain, last=True, output=archive_path, metadata=meta_path, workers=4, silent=True, progress=False
            )
        if "2y" in mode:
            backup = PyWayBackup(
                url=domain,
                all=True,
                range=2,
                output=archive_path,
                metadata=meta_path,
                workers=4,
                silent=True,
                progress=False,
            )
        backup.run()
        backup.paths()
        logger.info(msg=f"Downloaded [{mode}] archive code from URL [{domain}]", extra={"job_id": job_id})
        analyze_code(job_id, domain, archive_path, domain, "archive")
        return True
    except Exception as e:
        logger.error(msg=f"Error downloading archive:\n{e}", extra={"job_id": job_id}, exc_info=True)
        return False


def __db_read(job_id: str) -> list:
    url_list = []
    stmt = select(tbl_job.job_domain).where(tbl_job.job_id == job_id)
    url_list.append(database.db.session.execute(statement=stmt).scalar_one_or_none())
    stmt = select(tbl_hlink.c_hlink_link).where(tbl_hlink.job_id == job_id)
    url_list.extend(database.db.session.execute(statement=stmt).scalars().all())
    return url_list


def _request(mode: str, job_id: str, job_path: str):
    """
    Downloads source code or archived content for the given job's domain.

    Args:
        mode: One of 'source_index', 'source_full', 'archive_latest', 'archive_2y'.
        job_id: The unique identifier for the job.
        job_path: Filesystem path where job-related files are stored.
    """
    logger.info(msg=f"Request received mode [{mode}]", extra={"job_id": job_id})
    url_list = __db_read(job_id=job_id)
    if "source" in mode:
        source_path = f"{job_path}/code/source"
        __source(mode=mode, job_id=job_id, url_list=url_list, source_path=source_path)
    if "archive" in mode:
        archive_path = f"{job_path}/code/archive"
        meta_path = f"{job_path}/meta/waybackup"
        __archive(mode=mode, job_id=job_id, url_list=url_list, archive_path=archive_path, meta_path=meta_path)


def source_index(job_id: str, job_path: str):
    _request(mode="source_index", job_id=job_id, job_path=job_path)


def source_full(job_id: str, job_path: str):
    _request(mode="source_full", job_id=job_id, job_path=job_path)


def archive_latest(job_id: str, job_path: str):
    _request(mode="archive_latest", job_id=job_id, job_path=job_path)


def archive_2y(job_id: str, job_path: str):
    _request(mode="archive_2y", job_id=job_id, job_path=job_path)
