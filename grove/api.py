"""contains the routes for POST / GET by form or fetch"""

from datetime import datetime

from flask import Blueprint, Response, request, redirect, flash, send_file, url_for

import grove.services.util as util

from grove.db import database, get_all_tables, delete_tables, tbl_log
from grove.services.system.workflow.jobmaster import jm as jobmaster
from grove.extensions import logger


a = Blueprint("api", __name__)


@a.route("/api/task", methods=["POST"])
def api_task():
    task_target = request.form.get("task_target", None)
    if task_target:
        task_target = util.cleanup_url(user_input=task_target, cut_path=True)
        task_source = request.form.get("task_source", None)
        task_archive = request.form.get("task_archive", None)
        task_archive_start = request.form.get("task_archive_start", None)
        task_archive_end = request.form.get("task_archive_end", None)
        task_screenshot = request.form.get("task_screenshot", None)
        task_subdomain = request.form.get("task_subdomain", None)
        task_hyperlink = request.form.getlist("task_hyperlink[]", None)
        job_config = {
            "task_source": task_source,
            "task_archive": task_archive,
            "task_archive_start": task_archive_start,
            "task_archive_end": task_archive_end,
            "task_screenshot": task_screenshot,
            "task_subdomain": task_subdomain,
            "task_hyperlink": task_hyperlink,
        }
        if jobmaster.create_job(job_type="web", job_input=task_target, job_config=job_config):
            flash({"type": "alert", "color": "info", "msg": f"Job for [{task_target}] has been created"})
    return redirect(url_for("routes.index"))


@a.route("/api/jobs", methods=["POST"])
def api_jobs():
    result = request.form.get("result", None)
    download = request.form.get("download", None)
    restart = request.form.get("restart", None)
    delete = request.form.get("delete", None)
    if result:
        if jobmaster.get_job_status(result) == "done":
            return redirect(url_for("routes.results", id=result))
        flash({"type": "alert", "color": "warning", "msg": "Job is not ready to be viewed"})
    if download:
        logger.info(msg=f"Download has been requested for job [{download}]")
        return redirect(url_for("api.api_download", type="result", target=download))
    if restart:
        logger.info(msg=f"Restart has been requested for job [{restart}]")
        old_job = jobmaster.fetch_job(job_id=restart)
        jobmaster.del_job(job_id=old_job.job_id)
        jobmaster.create_job(
            job_type=old_job.job_type,
            job_input=old_job.job_input,
            job_config=old_job.job_config.raw,
        )
        flash({"type": "alert", "color": "info", "msg": f"Job {restart} has been restarted"})
        return redirect(url_for("routes.jobs"))
    if delete:
        logger.info(msg=f"Deletion has been requested for job [{delete}]")
        jobmaster.del_job(job_id=delete)
        flash({"type": "alert", "color": "info", "msg": f"Job {delete} has been deleted"})
        return redirect(url_for("routes.jobs"))
    return redirect("/jobs")


@a.route("/api/settings", methods=["POST"])
def api_settings():
    payload = request.form.get("settings", None)
    try:
        if payload == "prune_app":
            logger.info(msg="App prune has been requested")
            delete_tables(tables=get_all_tables())
            database.db.session.commit()
            jobmaster.clean_jobdir()
            from grove.services.system.search import drop_all
            drop_all()
            logger.info(msg="App has been pruned")
        if payload == "prune_log":
            logger.info(msg="Prune log has been requested")
            delete_tables(tables=["tbl_log"])
            logger.info(msg="Log has been pruned")

    except Exception as e:
        logger.error(msg=f"Prune failed:\n{e}", exc_info=True)
        flash({"type": "alert", "color": "danger", "msg": "Prune failed"})
        return redirect(url_for("routes.settings"))

    flash({"type": "alert", "color": "info", "msg": "Prune successfull"})
    return redirect(url_for("routes.settings"))


@a.route("/api/result", methods=["POST"])
def api_results():
    pass


@a.route("/api/log/download", methods=["GET"])
def api_log_download():
    """Stream the full tbl_log as a plain-text file (live-log only shows a tail)."""
    rows = database.db.session.query(tbl_log).order_by(tbl_log.id.asc()).all()
    body = "".join(
        f"{r.log_date} {r.log_level} {r.log_module}.{r.log_func} {r.log_msg}\n" for r in rows
    )
    filename = f"grove-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    return Response(
        body,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@a.route("/api/download", methods=["GET"])
def api_download():
    payload_dl_type = request.args.get("type")
    payload_dl_target = request.args.get("target", None)
    if payload_dl_type and payload_dl_target:
        if payload_dl_type == "result":
            job_zip = jobmaster.job_zip(payload_dl_target)
            if job_zip:
                return send_file(
                    job_zip, mimetype="application/zip", as_attachment=True, download_name=f"{payload_dl_target}.zip"
                )
            flash({"type": "alert", "color": "warning", "msg": "Download not available (Is the job ready?)"})
    return redirect("/jobs")
