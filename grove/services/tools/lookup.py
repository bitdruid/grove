import os
import socket

from grove.db import tbl_job, tbl_lookup
from grove.db import database, select

from grove.extensions import logger
from grove.services.tools.tool import Tool


class Lookup(Tool):

    name = "lookup"

    def db_read(self, job_id: str, **kwargs):
        domain, ip = database.db.session.execute(
            select(tbl_job.job_domain, tbl_job.job_ipv4).where(tbl_job.job_id == job_id)
        ).first()
        return domain, ip

    def run(self, job_id: str, data, **kwargs):
        domain, ip = data
        lookup_json = {}
        domain_whois = {}
        domain_response = {}
        ip_whois = {}
        ip_response = {}

        if ip:
            try:
                lookup_json["primary ipv4"] = ip
                lookup_json["primary ipv6"] = socket.getaddrinfo(ip, None, socket.AF_INET6)[0][4][0]
            except:
                pass
        if domain:
            try:
                lookup_json["domain"] = domain
                lookup_json["hostname"] = str(socket.gethostbyaddr(lookup_json["primary ipv4"])[0])
            except:
                pass

        if domain:
            domain_whois = os.popen("whois " + domain).read().lower()
        if ip:
            ip_whois = os.popen("whois " + ip).read().lower()

        whois_fields = {
            "domain_creation": "creation date:",
            "domain_registrar": "registrar:",
            "domain_network": "netname:",
            "domain_organization": "organization:",
            "ip_orgASN": ["origin:", "OriginAS:", "aut-num:"],
            "ip_country": "country:",
        }
        if domain_whois:
            domain_response = self._search_term(whois_fields, domain_whois)
        if ip_whois:
            ip_response = self._search_term(whois_fields, ip_whois)

        whois_response = domain_response | ip_response
        lookup_json = lookup_json | whois_response

        lookup_json["domain_whois"] = str(domain_whois)
        lookup_json["ip_whois"] = str(ip_whois)

        return lookup_json

    def db_write(self, job_id: str, result, **kwargs):
        try:
            ip_keys = ["primary ipv4", "primary ipv6", "ip_orgASN", "ip_country"]
            domain_keys = [
                "domain",
                "hostname",
                "domain_creation",
                "domain_registrar",
                "domain_network",
                "domain_organization",
            ]
            ip_response = "\n".join(f"{key}: {result[key]}" for key in ip_keys if key in result)
            domain_response = "\n".join(f"{key}: {result[key]}" for key in domain_keys if key in result)
            database.db.session.add(
                tbl_lookup(
                    job_id=job_id,
                    c_lookup_domain_data=domain_response,
                    c_lookup_domain_whois=result.get("domain_whois", ""),
                    c_lookup_ip_data=ip_response,
                    c_lookup_ip_whois=result.get("ip_whois", ""),
                )
            )
            database.db.session.commit()
        except Exception as e:
            logger.error(msg=f"Error saving to database:\n{e}", extra={"job_id": job_id}, exc_info=True)

    @staticmethod
    def _search_term(term: dict, whois_data=None) -> dict:
        def _search(term, whois_data):
            if term and term.lower() in whois_data:
                term = whois_data.split(term.lower())[1].split("\n")[0].strip()
                return term if term else False
            return False

        response = {}
        for key, value in term.items():
            if isinstance(value, list):
                for item in enumerate(value):
                    fieldvalue = _search(item[1], whois_data)
                    if fieldvalue:
                        response[key] = fieldvalue
            else:
                fieldvalue = _search(value, whois_data)
                if fieldvalue:
                    response[key] = fieldvalue
        return response


lookup = Lookup()
