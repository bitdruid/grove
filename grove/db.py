from os import getenv

import fcntl
import os
import subprocess
import threading

from hashlib import sha256
from datetime import datetime

from flask import Flask

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import insert, select, update, delete
from sqlalchemy.sql.schema import Table


_db = SQLAlchemy()


database = None


class tbl_log(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    log_date = _db.Column(_db.Text)
    log_level = _db.Column(_db.Text)
    log_module = _db.Column(_db.Text)
    log_func = _db.Column(_db.Text)
    log_job_id = _db.Column(_db.Text)
    log_msg = _db.Column(_db.Text)


class tbl_job(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, unique=True)
    job_date_start = _db.Column(_db.Text)
    job_date_end = _db.Column(_db.Text)
    job_type = _db.Column(_db.Text)  # web, mail
    job_input = _db.Column(_db.Text)
    job_domain = _db.Column(_db.Text)
    job_ipv4 = _db.Column(_db.Text)
    job_path = _db.Column(_db.Text)
    job_status = _db.Column(_db.Text, default="new")  # new, process, prepare, done, stuck, fail
    job_config = _db.Column(_db.Text)  # settings dict
    job_tasks = _db.Column(_db.Text)  # JSON list of {task, status} dicts
    job_task_id = _db.Column(_db.Text)  # Celery chain root task id (for revoke)
    job_bytes = _db.Column(_db.Integer, default=0)  # on-disk size, refreshed by the health check
    job_db_rows = _db.Column(_db.Integer, default=0)  # db row count, refreshed by the health check


class tbl_lookup(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, unique=True)
    c_lookup_domain_data = _db.Column(_db.Text)
    c_lookup_domain_whois = _db.Column(_db.Text)
    c_lookup_ip_data = _db.Column(_db.Text)
    c_lookup_ip_whois = _db.Column(_db.Text)


class tbl_record(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, unique=True)
    c_record_a = _db.Column(_db.Text)
    c_record_aaaa = _db.Column(_db.Text)


class tbl_subdomain(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, index=True)
    c_subdomain_name = _db.Column(_db.Text)
    c_subdomain_ipv4 = _db.Column(_db.Text)


class tbl_geoip(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, index=True)
    c_geoip_api = _db.Column(_db.Text)
    c_geoip_data = _db.Column(_db.Text)
    c_geoip_mapurl = _db.Column(_db.Text)


class tbl_screenshot(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, index=True)
    c_screenshot_url = _db.Column(_db.Text, unique=True)
    c_screenshot_thumb = _db.Column(_db.Text)
    c_screenshot_file = _db.Column(_db.Text)
    c_screenshot_pdf = _db.Column(_db.Text)


class tbl_code(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, index=True)
    c_code_url = _db.Column(_db.Text)
    c_code_file = _db.Column(_db.Text, unique=True)
    c_code_type = _db.Column(_db.Text)
    c_code_mime = _db.Column(_db.Text)
    c_code_hlink = _db.Column(_db.Text)
    c_code_meta = _db.Column(_db.Text)
    c_code_external = _db.Column(_db.Text)
    c_code_exif = _db.Column(_db.Text)
    c_code_gps = _db.Column(_db.Text)
    c_code_ocr = _db.Column(_db.Text)
    c_code_mail = _db.Column(_db.Text)
    c_code_phone = _db.Column(_db.Text)


class tbl_finding(_db.Model):
    # single store for scraped contacts: one row per (value, source, location) hit
    # (mail now; phone/account/crypto later). Distinct values give the address list.
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, index=True)
    c_finding_kind = _db.Column(_db.Text)      # mail | phone | account | crypto
    c_finding_value = _db.Column(_db.Text)     # the extracted value
    c_finding_source = _db.Column(_db.Text)    # code | ocr | exif
    c_finding_location = _db.Column(_db.Text)  # file path where it was found
    __table_args__ = (
        _db.UniqueConstraint(
            "job_id", "c_finding_kind", "c_finding_value", "c_finding_source", "c_finding_location",
            name="uq_finding",
        ),
    )


class tbl_hlink(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, index=True)
    c_hlink_link = _db.Column(_db.Text, unique=True)
    c_hlink_local = _db.Column(_db.Text)  # relative path under jobs/ if a local HTML copy exists


class tbl_meta(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, index=True)
    c_meta_tag = _db.Column(_db.Text, unique=True)


class tbl_external(_db.Model):
    id = _db.Column(_db.Integer, primary_key=True)
    job_id = _db.Column(_db.Text, index=True)
    c_external_link = _db.Column(_db.Text, unique=True)


def get_all_tables(exclude: list = None) -> list[Table]:
    """
    Return a list of table objects and optionally exclude a given list of table names.
    """
    tables = []
    metadata = _db.metadata
    for table in reversed(metadata.sorted_tables):
        if exclude and table.name in exclude:
            continue
        tables.append(table)
    return tables


def delete_tables(tables: list[Table | str]):
    """
    Delete all rows in the given tables.
    """
    # convert string table names into table-objects
    tables = [_db.metadata.tables[t] if isinstance(t, str) else t for t in tables]
    for table in tables:
        _db.session.execute(delete(table))
    _db.session.commit()


class Database:
    def __init__(self):
        self.db = _db

    def init_app(self, flask: Flask):
        """Initialize the database with Flask application."""
        flask.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///db.sqlite3"
        flask.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        flask.secret_key = sha256(str(datetime.now()).encode("utf-8")).hexdigest()
        flask.config["SESSION_TYPE"] = "filesystem"
        self.db.init_app(flask)
        with flask.app_context():
            self._create_all_locked(flask)
        self.init_browser(flask) if getenv("SQLITE_WEB", "1") == "1" else None

    def _create_all_locked(self, flask: Flask):
        """
        create_all() guarded by a cross-process lock. Web and worker
        processes both init on startup, so serialize to avoid a race on the fresh SQLite file.
        """
        os.makedirs(flask.instance_path, exist_ok=True)
        with open(os.path.join(flask.instance_path, ".dbinit.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self.db.create_all()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def init_browser(self, flask: Flask):
        """Start simple sqlite browser for the db."""
        sqlite_web_thread = threading.Thread(
            target=subprocess.run,
            args=(
                [
                    "sqlite_web",
                    "--no-browser",
                    "--host=0.0.0.0",
                    "--port=5001",
                    flask.instance_path + "/" + flask.config["SQLALCHEMY_DATABASE_URI"].lstrip("sqlite:///"),
                ],
            ),
            kwargs={"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL},
            daemon=True,
        )
        sqlite_web_thread.start()


database = Database()
