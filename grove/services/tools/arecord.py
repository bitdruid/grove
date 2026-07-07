import dns.resolver

from grove.db import select, tbl_job, tbl_record
from grove.db import database

from grove.extensions import logger
from grove.services.tools.tool import Tool


class ARecord(Tool):

    name = "arecord"

    def db_read(self, job_id: str, **kwargs):
        domain = database.db.session.execute(
            select(tbl_job.job_domain).where(tbl_job.job_id == job_id)
        ).scalar_one_or_none()
        return domain

    def run(self, job_id: str, data, **kwargs):
        domain = data

        if not domain:
            return None

        resolver = dns.resolver.Resolver()
        resolver.nameservers = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]

        response = {}

        try:
            response["A"] = [str(record) for record in resolver.resolve(domain, "A")]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            pass

        try:
            response["AAAA"] = [str(record) for record in resolver.resolve(domain, "AAAA")]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            pass

        return response

    def db_write(self, job_id: str, result, **kwargs):
        if not result:
            return
        try:
            database.db.session.add(
                tbl_record(
                    job_id=job_id,
                    c_record_a="\n".join(result.get("A", "")),
                    c_record_aaaa="\n".join(result.get("AAAA", "")),
                )
            )
            database.db.session.commit()
        except Exception as e:
            logger.error(msg=f"Error saving to database:\n{e}", extra={"job_id": job_id}, exc_info=True)


arecord = ARecord()
