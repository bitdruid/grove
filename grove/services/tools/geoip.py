import requests

from grove.db import tbl_job, tbl_geoip
from grove.db import database, select

from grove.extensions import logger
from grove.services.tools.tool import Tool


class Geoip(Tool):

    name = "geoip"

    def db_read(self, job_id: str, **kwargs):
        ip = database.db.session.execute(select(tbl_job.job_ipv4).where(tbl_job.job_id == job_id)).scalars().first()
        return ip

    def run(self, job_id: str, data, **kwargs):
        ip = data
        geoip_data = self._query_api(job_id, ip)
        geoip_data = self._filter_response(job_id, geoip_data)
        geoip_data = self._convert_coords_to_url(job_id, geoip_data)
        return geoip_data

    def db_write(self, job_id: str, result, **kwargs):
        try:
            database.db.session.add_all(
                [
                    tbl_geoip(
                        job_id=job_id,
                        c_geoip_api=entry["api"],
                        c_geoip_data="\n".join(f"{key.ljust(8)}: {value}" for key, value in entry["geoip_data"].items()),
                        c_geoip_mapurl=entry["map_url"],
                    )
                    for entry in result
                ]
            )
            database.db.session.commit()
        except Exception as e:
            logger.error(msg=f"Error saving to database:\n{e}", extra={"job_id": job_id}, exc_info=True)

    def _query_api(self, job_id: str, ip: str) -> list[dict]:
        # Free, no-API-key geolocation endpoints. All return JSON with lat/lon.
        api_dict = {
            "ipwho.is":       "https://ipwho.is/{ip}",
            "ip-api.com":     "http://ip-api.com/json/{ip}",
            "freeipapi.com":  "https://free.freeipapi.com/api/json/{ip}",
            "geojs.io":       "https://get.geojs.io/v1/ip/geo/{ip}.json",
        }

        try:
            api_data = []
            for api, api_url in api_dict.items():
                user_agent = "Mozilla/5.0"
                response = requests.get(api_url.format(ip=ip), headers={"User-Agent": user_agent})
                if response.status_code == 200:
                    api_data.append({"api": api, "geoip_data": response.json(), "map_url": ""})
                else:
                    logger.warning(msg=f"API [{api}] did not respond", extra={"job_id": job_id})
            return api_data
        except Exception as e:
            logger.error(msg=f"Error requesting API [{api}]:\n{e}", extra={"job_id": job_id}, exc_info=True)
            return api_data

    def _filter_response(self, job_id: str, geoip_data: list[dict]) -> list[dict]:
        try:
            geoip_data_new = []
            for entry in geoip_data:
                data = entry["geoip_data"]
                if data:
                    valid_keys = ["country", "region", "state", "city", "latitude", "longitude"]
                    rename_keys = {
                        "country_name": "country",
                        "countryName":  "country",
                        "region_name":  "region",
                        "regionName":   "region",
                        "cityName":     "city",
                        "lat":          "latitude",
                        "lon":          "longitude",
                    }
                    filtered_response = {}
                    for key, value in data.items():
                        if key in valid_keys:
                            filtered_response[key] = value
                        elif key in rename_keys:
                            filtered_response[rename_keys[key]] = value
                    geoip_data_new.append({"api": entry["api"], "geoip_data": filtered_response, "map_url": ""})
            return geoip_data_new
        except Exception as e:
            logger.error(msg=f"Error filtering geoip keys [{entry}]:\n{e}", extra={"job_id": job_id}, exc_info=True)
            return geoip_data_new

    def _convert_coords_to_url(self, job_id: str, geoip_data: list[dict]) -> list[dict]:
        try:
            geoip_data_new = []
            for entry in geoip_data:
                data = entry["geoip_data"]
                if data:
                    topo_url = "https://opentopomap.org/#marker=7/{latitude}/{longitude}"
                    topo_url = topo_url.format(latitude=data["latitude"], longitude=data["longitude"])
                    del data["latitude"]
                    del data["longitude"]
                    data = {key: data[key] for key in sorted(data.keys())}
                    geoip_data_new.append({"api": entry["api"], "geoip_data": data, "map_url": topo_url})
            return geoip_data_new
        except Exception as e:
            logger.error(msg=f"Error converting coordinates [{entry}]:\n{e}", extra={"job_id": job_id}, exc_info=True)
            return geoip_data_new


geoip = Geoip()
