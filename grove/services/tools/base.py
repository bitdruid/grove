from playwright.sync_api import sync_playwright
from grove.db import database, tbl_base
import grove.services.validation as validation
from grove.extensions import logger
from grove.services.tools.tool import Tool


class Base(Tool):

    name = "base"

    def run(self, job_id: str, data, **kwargs):
        query_input = kwargs["query_input"]

        data_dict = {}
        domain, ip = validation.get_primary(query_input)
        data_dict["domain"] = domain if domain else ""
        data_dict["ipv4"] = ip if ip else ""

        try:
            url = data_dict.get("domain", None)
            if url:
                with sync_playwright() as playwright:
                    browser = playwright.firefox.launch(headless=True)
                    browser = browser.new_context(
                        user_agent="""
                        Mozilla/5.0 (Windows NT 10.0; Win64; x64)
                        AppleWebKit/537.36 (KHTML, like Gecko)
                        Chrome/58.0.3029.110
                        Safari/537.3
                        """,
                        viewport={"width": 1600, "height": 900},
                    )
                    page = browser.new_page()
                    page.goto(f"http://{url}")
                    page.wait_for_load_state("domcontentloaded")
                    data_dict["index"] = page.content()
                    browser.close()
        except Exception as e:
            logger.error(msg=f"Error scraping index.html:\n{e}", extra={"job_id": job_id}, exc_info=True)

        return data_dict

    def db_write(self, job_id: str, result, **kwargs):
        try:
            database.db.session.add(
                tbl_base(
                    job_id=job_id,
                    base_domain=result.get("domain", ""),
                    base_ipv4=result.get("ipv4", ""),
                    base_index=result.get("index", ""),
                )
            )
            database.db.session.commit()
        except Exception as e:
            logger.error(msg=f"Error saving to database:\n{e}", extra={"job_id": job_id}, exc_info=True)


base = Base()
