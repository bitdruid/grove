import sys
import json
import subprocess

import dns.resolver

from grove.db import select, tbl_job, tbl_subdomain
from grove.db import database

from grove.extensions import logger
from grove.services.system.subprocess import spawn
from grove.services.tools.tool import Tool


# Sublist3r enumerates search engines with `multiprocessing`. Celery prefork
# workers are daemonic and daemonic processes may not spawn children, so calling
# it in-process yields nothing. Running it in a fresh (non-daemonic) subprocess
# sidesteps that, and `spawn` puts it in its own process group so the task's
# SIGTERM handler tears the whole tree down on cancellation.
_RUNNER = (
    "import json, sys, sublist3r; "
    "print(json.dumps(sublist3r.run(sys.argv[1], output='list', bruteforce=False, silent=True)))"
)


class Subdomain(Tool):
    """Enumerate subdomains for a domain via Sublist3r and resolve each to an IPv4."""

    name = "subdomain"

    def db_read(self, job_id: str, **kwargs):
        domain = database.db.session.execute(
            select(tbl_job.job_domain).where(tbl_job.job_id == job_id)
        ).scalar_one_or_none()
        return domain

    def run(self, job_id: str, data, **kwargs):
        domain = data

        if not domain:
            return None

        try:
            proc = spawn([sys.executable, "-c", _RUNNER, domain], stdout=subprocess.PIPE)
            out, _ = proc.communicate()
            # silent=True keeps the runner quiet, so stdout is just the JSON line.
            line = out.decode("utf-8", errors="replace").strip().splitlines()
            subdomains = json.loads(line[-1]) if line else []
        except Exception as e:
            logger.error(msg=f"Error enumerating subdomains:\n{e}", extra={"job_id": job_id}, exc_info=True)
            return None

        resolver = dns.resolver.Resolver()
        resolver.nameservers = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]
        resolver.lifetime = 5.0

        result = []
        for sub in sorted(set(subdomains)):
            ipv4 = ""
            try:
                ipv4 = ", ".join(str(record) for record in resolver.resolve(sub, "A"))
            except Exception:
                # NXDOMAIN / NoAnswer / Timeout — keep the subdomain, leave IP empty
                pass
            result.append({"name": sub, "ipv4": ipv4})

        logger.info(msg=f"Found {len(result)} subdomains for [{domain}]", extra={"job_id": job_id})
        return result

    def db_write(self, job_id: str, result, **kwargs):
        if not result:
            return
        try:
            database.db.session.add_all(
                [
                    tbl_subdomain(
                        job_id=job_id,
                        c_subdomain_name=entry["name"],
                        c_subdomain_ipv4=entry["ipv4"],
                    )
                    for entry in result
                ]
            )
            database.db.session.commit()
        except Exception as e:
            logger.error(msg=f"Error saving to database:\n{e}", extra={"job_id": job_id}, exc_info=True)


subdomain = Subdomain()
