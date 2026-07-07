"""contains the routes to direct html-files"""

import os
import shutil
from csv import reader
from importlib.metadata import version

from flask import Blueprint, redirect, render_template, request, send_from_directory, url_for

from grove.db import tbl_job
from grove.config import Config
from grove.services.system.workflow.jobmaster import jm as jobmaster


r = Blueprint("routes", __name__)


@r.route("/")
def index():
    return render_template("index.html", indexdata=indexdata())


@r.route("/jobs")
def jobs():
    import json

    def _human_bytes(n: int) -> str:
        n = float(n or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
            n /= 1024

    result = tbl_job.query.all()
    for job in result:
        tasks = json.loads(job.job_tasks) if job.job_tasks else []
        total = len(tasks)
        done = sum(1 for t in tasks if t["status"] == "done")
        job.progress = int((done / total) * 100) if total > 0 else 0
        job.tasks = tasks
        job.size_human = _human_bytes(job.job_bytes)
        job.db_rows = job.job_db_rows or 0
    return render_template("index.html", indexdata=indexdata(), job_list=result)


@r.route("/data/<path:filename>")
def data(filename: str):
    jobs_root = os.path.abspath("jobs")
    # strip optional leading "jobs/" so we can serve both
    # /data/<job_id>/... and /data/jobs/<job_id>/... (DB stores the latter)
    rel = filename[5:] if filename.startswith("jobs/") else filename
    full = os.path.abspath(os.path.join(jobs_root, rel))
    if not full.startswith(jobs_root + os.sep) or not os.path.isfile(full):
        return redirect(url_for("routes.jobs"))
    kwargs = {}
    if request.args.get("as") == "html":
        kwargs["mimetype"] = "text/html; charset=utf-8"
    return send_from_directory(jobs_root, rel, **kwargs)


@r.route("/result")
def results():
    payload_job_id = request.args.get("id", None)
    if payload_job_id:
        job_data = jobmaster.get_all_job_data(job_id=payload_job_id, only_completed=True)
        return render_template("index.html", indexdata=indexdata(), job_data=job_data)
    return redirect(url_for("routes.jobs"))


@r.route("/search")
def search():
    from grove.services.system.search import search_all
    query = request.args.get("q", "").strip()
    results = search_all(query) if query else []
    return render_template(
        "index.html", indexdata=indexdata(), search_query=query, search_results=results
    )


# How much of a file the formatted viewer renders. Browsers (and highlight.js)
# choke on huge files, and search hits are about locating, not bulk reading.
VIEW_MAX_CHARS = 2 * 1024 * 1024


@r.route("/view")
def view():
    """Formatted, syntax-highlighted file view with the search term marked."""
    jobs_root = os.path.abspath("jobs")
    filename = request.args.get("path", "")
    rel = filename[5:] if filename.startswith("jobs/") else filename
    full = os.path.abspath(os.path.join(jobs_root, rel))
    if not full.startswith(jobs_root + os.sep) or not os.path.isfile(full):
        return redirect(url_for("routes.jobs"))
    with open(full, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read(VIEW_MAX_CHARS + 1)
    truncated = len(content) > VIEW_MAX_CHARS
    return render_template(
        "index.html",
        indexdata=indexdata(),
        view_file=rel,
        view_content=content[:VIEW_MAX_CHARS],
        view_truncated=truncated,
        view_query=request.args.get("q", ""),
    )


@r.route("/settings")
def settings():
    return render_template("index.html", indexdata=indexdata())


def indexdata():
    indexdata = {
        "footer_url": "https://github.com/bitdruid",
        "footer_author": "bitdruid",
        "footer_version": version("Grove"),
        "footer_sources": read_sources(),
        "job_counting": jobmaster.count_jobs(),
        "disk_space": dict(zip(("total", "used", "free"), (int(x / 1024**3) for x in shutil.disk_usage("jobs/")))),
        "sqlite_web": os.getenv("SQLITE_WEB", "1") == "1",
        "sqlite_web_port": os.getenv("SQLITE_WEB_PORT", "5001"),
    }
    return indexdata


def read_sources():
    sources_list = []
    with open(Config.SOURCES, "r", encoding="utf-8") as file:
        csv_content = reader(file)
        for line in csv_content:
            sources_list.append({"use": line[0], "author": line[1], "name": line[2], "origin": line[3]})
        return sources_list
