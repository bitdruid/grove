import os
from datetime import datetime

from playwright.sync_api import sync_playwright

import grove.services.validation as validation
from grove.services.util import sanitize_filename, img2a4pdf, img2thumb

from grove.db import database, insert
from grove.db import tbl_screenshot, tbl_hlink

from grove.extensions import logger
from grove.services.tools.tool import Tool


class Screenshot(Tool):

    name = "screenshot"

    def db_read(self, job_id: str, **kwargs):
        new_list = []
        url_list = tbl_hlink.query.with_entities(tbl_hlink.c_hlink_link).filter_by(job_id=job_id).all()
        url_list = [url for (url,) in url_list]
        for url in url_list:
            if validation.validate_domain(url):
                new_list.append(url)
        return new_list

    def run(self, job_id: str, data, **kwargs):
        job_input = kwargs["job_input"]
        job_path = kwargs["job_path"]
        mode = kwargs.get("mode", "index")

        url_list = [validation.get_primary(job_input)[0]]
        if mode == "full":
            url_list.extend(data)

        screenshot_list = []
        try:
            os.makedirs(os.path.join(job_path, "screenshots"), exist_ok=True)
            with sync_playwright() as playwright:
                try:
                    browser = playwright.firefox.launch(headless=True)
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/58.0.3029.110 Safari/537.3",
                        viewport={"width": 1600, "height": 900},
                    )
                    page = context.new_page()

                    for url in url_list:
                        try:
                            if not validation.reachable(url):
                                logger.warning(
                                    msg=f"Can't screenshot - url seems offline {[url]}",
                                    extra={"job_id": job_id},
                                )
                                continue

                            page.goto(f"http://{url}")
                            page.wait_for_timeout(1000)

                            screenshot_file = (
                                f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{sanitize_filename(url)}.jpeg"
                            )
                            screenshot_file = os.path.join(job_path, "screenshots", screenshot_file)

                            page.screenshot(path=screenshot_file, full_page=True, type="jpeg", quality=80)
                            logger.debug(
                                msg=f"Screenshot [{os.path.basename(screenshot_file)}] - url [{url}]",
                                extra={"job_id": job_id},
                            )

                            pdf_file = img2a4pdf(screenshot_file, job_id=job_id)
                            logger.debug(
                                msg=f"PDF [{os.path.basename(pdf_file)}] - url [{url}]",
                                extra={"job_id": job_id},
                            )

                            thumb_file = img2thumb(screenshot_file, job_id=job_id)
                            logger.debug(
                                msg=f"Thumbnail [{os.path.basename(thumb_file)}] - url [{url}]",
                                extra={"job_id": job_id},
                            )

                            if screenshot_file and pdf_file:
                                self._save(job_id, url, thumb_file, screenshot_file, pdf_file)
                                screenshot_list.append([url, thumb_file, screenshot_file, pdf_file])

                        except Exception as e:
                            logger.error(
                                msg=f"Error creating screenshot of {url}:\n{e}",
                                extra={"job_id": job_id},
                                exc_info=True,
                            )

                    context.close()
                    browser.close()

                except Exception as e:
                    logger.error(
                        msg=f"Playwright/Browser setup failed: {e}",
                        extra={"job_id": job_id},
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(
                msg=f"Playwright initialization failed: {e}",
                extra={"job_id": job_id},
                exc_info=True,
            )

        return screenshot_list

    def _save(self, job_id, url, thumb_file, screenshot_file, pdf_file):
        try:
            database.db.session.execute(
                insert(tbl_screenshot)
                .prefix_with("OR IGNORE")
                .values(
                    job_id=job_id,
                    c_screenshot_url=url,
                    c_screenshot_thumb=thumb_file,
                    c_screenshot_file=screenshot_file,
                    c_screenshot_pdf=pdf_file,
                )
            )
            database.db.session.commit()
        except Exception as e:
            logger.error(msg=f"Error saving to database [{screenshot_file}]:\n{e}", extra={"job_id": job_id}, exc_info=True)
            database.db.session.rollback()


screenshot = Screenshot()
