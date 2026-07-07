from __future__ import annotations

import os
import re

from grove.extensions import logger
from grove.services.system.subprocess import spawn
from grove.services.tools.tool import Tool


class OfflineResult(Tool):

    name = "offline_result"

    def run(self, job_id: str, data, **kwargs):
        job_path = kwargs["job_path"]

        try:
            query_string = f"result?id={job_id}"
            internal_url = f"http://127.0.0.1:5000/{query_string}"
            proc = spawn(
                [
                    "wget",
                    "--quiet",
                    f"--directory-prefix={job_path}/result",
                    "--no-host-directories",
                    "--cut-dirs=0",
                    "--convert-links",
                    "--page-requisites",
                    "--no-parent",
                    "--recursive",
                    "--level=1",
                    internal_url,
                ]
            )
            logger.debug(msg=f"Spawned wget process with URL [{internal_url}]", extra={"job_id": job_id})
            proc.wait()

            html_wrong = f"{job_path}/result/{query_string}"
            html_right = f"{job_path}/result/result.html"
            os.rename(html_wrong, html_right)
            os.remove(f"{job_path}/result/jobs")
            os.remove(f"{job_path}/result/settings")
            os.remove(f"{job_path}/result/index.html")

            with open(html_right, "r+", encoding="utf-8") as file:
                html = file.read()
                html = re.sub(r"<nav[\s\S]*?</nav>", "", html, flags=re.IGNORECASE)
                file.seek(0)
                file.write(html)
                file.truncate()

            # Shortcut at the job-folder root so users (and anyone unzipping the
            # bundle) can open the result without digging into result/. Relative
            # url keeps it portable across the live dir and extracted zips.
            with open(f"{job_path}/open_result.html", "w", encoding="utf-8") as shortcut:
                shortcut.write(
                    "<!doctype html>\n"
                    '<meta charset="utf-8">\n'
                    '<meta http-equiv="refresh" content="0; url=result/result.html">\n'
                    "<title>Opening result…</title>\n"
                    '<a href="result/result.html">Open result</a>\n'
                )

            return True
        except Exception as e:
            logger.error(msg=f"Error generating offline-result:\n{e}", extra={"job_id": job_id}, exc_info=True)
            return False


offline_result = OfflineResult()
