import os
from urllib.parse import unquote, urlparse

import easyocr

from grove.db import insert, select, update, tbl_code, tbl_hlink, tbl_meta, tbl_external, tbl_finding
from grove.db import database
from grove.extensions import logger
from grove.services.util import (
    extract_externals,
    extract_hyperlinks,
    extract_metatags,
    get_mime_type,
    ocr_image,
    ocr_pdf,
    exif_data,
    extract_mail,
)


def analyze_code(job_id: str, url: str, source_path: str, code_url: str, code_type: str):
    """
    Stores the source code for a job in the database. Determines mime-type and extracts hyperlinks, metatags and external sources.
    Args:
        job_id (str): The ID of the job.
        url (str): The url where the file was downloaded from.
        source_path (str): The path to the directory containing the source code files.
        code_url (str): The root-URL where the source code was downloaded from. Could be the user-input like "example.com".
        code_type (str): The type of code, such as "source" or "archive".
    """

    def __hyperlink(page_html: str, job_id: str, base_url: str | None = None):
        """
        Extracts all hyperlinks from the given HTML, stores them in tbl_hlink, and returns them as a newline-separated string.
        """
        values = []
        hyperlink_list = extract_hyperlinks(page_html=page_html, job_id=job_id, base_url=base_url)
        if hyperlink_list:
            values.extend([{"job_id": job_id, "c_hlink_link": link} for link in hyperlink_list])
            stmt = insert(tbl_hlink).values(values).prefix_with("OR IGNORE")
            database.db.session.execute(statement=stmt)
            database.db.session.commit()
            return "\n".join(hyperlink_list)
        return None

    def __metatag(page_html: str, job_id: str):
        """
        Extracts all HTML meta tags from the given HTML, stores them in tbl_meta, and returns them as a newline-separated string.
        """
        values = []
        metatag_list = extract_metatags(page_html=page_html, job_id=job_id)
        if metatag_list:
            values.extend([{"job_id": job_id, "c_meta_tag": tag} for tag in metatag_list])
            stmt = insert(tbl_meta).values(values).prefix_with("OR IGNORE")
            database.db.session.execute(statement=stmt)
            database.db.session.commit()
            return "\n".join(metatag_list)
        return None

    def __external(page_html: str, job_id: str, url: str):
        """
        Extracts all external resource links from the given HTML (excluding the job's domain),
        stores them in tbl_external, and returns them as a newline-separated string.
        """
        values = []
        external_list = extract_externals(page_html=page_html, job_id=job_id, skip_url=url)
        if external_list:
            values.extend([{"job_id": job_id, "c_external_link": external} for external in external_list])
            stmt = insert(tbl_external).values(values).prefix_with("OR IGNORE")
            database.db.session.execute(statement=stmt)
            database.db.session.commit()
            return "\n".join(external_list)
        return None

    try:
        logger.info(msg=f"Storing [{code_type}] code into db from URL [{code_url}]", extra={"job_id": job_id})
        rows = []
        for root, _, files in os.walk(source_path):
            for file in files:
                file_path = os.path.join(root, file)
                if not os.path.isfile(file_path):
                    continue
                rel_path = os.path.relpath(file_path, source_path)
                code_file = os.path.join(source_path, rel_path)
                code_mime = get_mime_type(code_file, job_id=job_id)
                hyperlink_list = None
                metatag_list = None
                external_list = None
                if "html" in code_mime:
                    with open(code_file, "r", encoding="utf-8") as file:
                        page_html = file.read()
                        page_url = _local_to_url(source_path, code_file)
                        hyperlink_list = __hyperlink(page_html=page_html, job_id=job_id, base_url=page_url)
                        metatag_list = __metatag(page_html=page_html, job_id=job_id)
                        external_list = __external(page_html=page_html, job_id=job_id, url=url)
                logger.debug(msg=f"Added [{code_mime}] - [{code_file.split(source_path)[1]}]", extra={"job_id": job_id})
                rows.append(
                    {
                        "job_id": job_id,
                        "c_code_url": code_url,
                        "c_code_file": code_file,
                        "c_code_type": code_type,
                        "c_code_mime": code_mime,
                        "c_code_hlink": hyperlink_list,
                        "c_code_meta": metatag_list,
                        "c_code_external": external_list,
                    }
                )
        if rows:
            stmt = insert(tbl_code).values(rows).prefix_with("OR IGNORE")
            database.db.session.execute(statement=stmt)
            database.db.session.commit()
            logger.info(msg=f"Code [{code_type}] done", extra={"job_id": job_id})
        else:
            logger.warning(msg=f"No [{code_type}] files found", extra={"job_id": job_id})

    except Exception as e:
        logger.error(msg=f"Error storing [{code_type}] code:\n{e}", extra={"job_id": job_id}, exc_info=True)
        database.db.session.rollback()


def get_img_ocr(job_id: str):
    """
    Stores the OCR text for images for a job in the database.
    """

    def __init_easyocr() -> easyocr.Reader:
        """
        Initializes and returns an EasyOCR Reader instance.
        """
        return easyocr.Reader(["en", "de"], gpu=False)

    try:
        logger.info(msg="Storing IMG OCR", extra={"job_id": job_id})
        ocr = __init_easyocr()
        logger.debug(msg="EasyOCR initialized", extra={"job_id": job_id})
        code_entries = tbl_code.query.filter(tbl_code.job_id == job_id, tbl_code.c_code_mime.ilike("%image%")).all()
        if code_entries:
            for entry in code_entries:
                ocr_text = ocr_image(ocr, entry.c_code_file, job_id=job_id)
                if ocr_text:
                    entry.c_code_ocr = ocr_text
                    logger.debug(
                        msg=f"IMG OCR added for file [{os.path.basename(entry.c_code_file)}]", extra={"job_id": job_id}
                    )
            database.db.session.commit()
        else:
            logger.warning(msg="No image files found for OCR", extra={"job_id": job_id})
        logger.info(msg="IMG OCR done", extra={"job_id": job_id})

    except Exception as e:
        logger.error(msg=f"Error storing IMG OCR:\n{e}", extra={"job_id": job_id}, exc_info=True)
        database.db.session.rollback()


def get_pdf_ocr(job_id: str):
    """
    Stores the OCR text for PDF files for a job in the database.
    """
    try:
        logger.info(msg="Storing PDF OCR", extra={"job_id": job_id})
        code_entries = tbl_code.query.filter(tbl_code.job_id == job_id, tbl_code.c_code_mime.ilike("%pdf%")).all()
        for entry in code_entries:
            ocr_text = ocr_pdf(entry.c_code_file, job_id=job_id)
            if ocr_text:
                entry.c_code_ocr = ocr_text
                logger.debug(
                    msg=f"PDF OCR added for file [{os.path.basename(entry.c_code_file)}]", extra={"job_id": job_id}
                )
        database.db.session.commit()
        logger.info(msg="PDF OCR done", extra={"job_id": job_id})

    except Exception as e:
        logger.error(msg=f"Error storing PDF OCR:\n{e}", extra={"job_id": job_id}, exc_info=True)
        database.db.session.rollback()


# Document MIME types for exiftool (media matched by prefix). Exact match avoids the "xml"-in-"openxmlformats" substring trap.
_EXIF_DOC_MIMES = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
        "application/rtf",
        "application/zip",  # OOXML/ODF are zip containers libmagic sometimes reports as plain zip; exiftool still reads them
    }
)


def _wants_exif(mime: str) -> bool:
    """True for media/documents whose embedded metadata is worth extracting.
    Web assets (html/css/js) are skipped — their metadata is either trivial or
    already captured by extract_metatags."""
    return mime.startswith(("image/", "video/", "audio/")) or mime in _EXIF_DOC_MIMES


def get_exif(job_id: str):
    """
    Extract embedded metadata from scraped media/documents via a single exiftool
    run and store it in tbl_code.c_code_exif, with any GPS tags mirrored into
    c_code_gps. Only image/audio/video and document types are considered (see
    _wants_exif). Runs before the mail step, which also scans c_code_exif for
    email addresses.
    """
    try:
        logger.info(msg="Storing EXIF metadata", extra={"job_id": job_id})
        code_entries = tbl_code.query.filter(tbl_code.job_id == job_id).all()
        files = [
            e.c_code_file
            for e in code_entries
            if e.c_code_file and _wants_exif(e.c_code_mime or "") and os.path.isfile(e.c_code_file)
        ]

        exif_map = exif_data(files, job_id=job_id)

        for entry in code_entries:
            text = exif_map.get(os.path.abspath(entry.c_code_file)) if entry.c_code_file else None
            if text:
                entry.c_code_exif = text
                # pull GPS tags into their own column (exiftool prefixes them "GPS ...")
                gps = "\n".join(line for line in text.split("\n") if line.startswith("GPS"))
                entry.c_code_gps = gps or None
        database.db.session.commit()
        logger.info(msg=f"EXIF done — {len(exif_map)} files with metadata", extra={"job_id": job_id})

    except Exception as e:
        logger.error(msg=f"Error storing EXIF:\n{e}", extra={"job_id": job_id}, exc_info=True)
        database.db.session.rollback()


def _local_to_url(source_path: str, file_path: str) -> str | None:
    """Reconstruct an https URL from a wget-saved file path under <source_path>/<host>/<rel>."""
    try:
        rel = os.path.relpath(file_path, source_path).replace(os.sep, "/")
    except ValueError:
        return None
    if not rel or rel.startswith(".."):
        return None
    host, _, path = rel.partition("/")
    if not host:
        return None
    return f"https://{host}/{path}"


def resolve_hlink_locals(job_id: str, job_path: str):
    """
    For each stored hyperlink, set c_hlink_local to the path (relative to cwd) of a
    matching locally-saved HTML file under <job_path>/code/source/<host>/<path>, if
    such a file exists and looks like HTML. Lets the result page offer an
    "open as html" action for links wget actually downloaded.
    """
    source_root = os.path.join(job_path, "code", "source")
    if not os.path.isdir(source_root):
        return

    rows = database.db.session.query(tbl_hlink).filter_by(job_id=job_id).all()
    abs_source = os.path.abspath(source_root)
    for row in rows:
        row.c_hlink_local = _map_link_to_local(row.c_hlink_link, source_root, abs_source)
    database.db.session.commit()


def _map_link_to_local(link: str, source_root: str, abs_source: str) -> str | None:
    if not link:
        return None
    raw = link if "://" in link else f"http://{link}"
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if not parsed.hostname:
        return None
    rel_path = unquote(parsed.path or "/")
    if rel_path.endswith("/") or not rel_path:
        rel_path = (rel_path + "index.html").lstrip("/")
    else:
        rel_path = rel_path.lstrip("/")
    candidate = os.path.normpath(os.path.join(source_root, parsed.hostname, rel_path))
    if not os.path.abspath(candidate).startswith(abs_source + os.sep):
        return None
    if not os.path.isfile(candidate):
        return None
    try:
        with open(candidate, "rb") as f:
            head = f.read(512).lstrip().lower()
    except OSError:
        return None
    if not (head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head[:512]):
        return None
    return candidate


def get_content_mail(job_id: str):
    """
    Check the text content, OCR and EXIF for email addresses.
    """

    def __mail(entry_content, source):
        if not isinstance(entry_content, str):
            return []
        logger.debug(msg=f"Checking file [{os.path.basename(entry.c_code_file)}]", extra={"job_id": job_id})
        mails = extract_mail(text_content=entry_content, job_id=job_id)
        if mails:
            # one row per (address, source, file); distinct values drive the accordion
            findings = [
                {
                    "job_id": job_id,
                    "c_finding_kind": "mail",
                    "c_finding_value": mail,
                    "c_finding_source": source,
                    "c_finding_location": entry.c_code_file,
                }
                for mail in mails
            ]
            database.db.session.execute(insert(tbl_finding).values(findings).prefix_with("OR IGNORE"))
            database.db.session.commit()
        return mails

    try:
        logger.info(msg="Storing email addresses", extra={"job_id": job_id})

        stmt = select(tbl_code).where(tbl_code.job_id == job_id)
        code_entries = database.db.session.execute(stmt).scalars().all()

        for entry in code_entries:
            if os.path.exists(entry.c_code_file):
                mail_list = []
                if "text" in entry.c_code_mime or "xml" in entry.c_code_mime or "json" in entry.c_code_mime:
                    with open(entry.c_code_file, "r", encoding="utf-8", errors="ignore") as file:
                        entry_content = file.read()
                        mail_list.extend(__mail(entry_content, "code"))
                else:
                    mail_list.extend(__mail(entry.c_code_ocr, "ocr"))
                    mail_list.extend(__mail(entry.c_code_exif, "exif"))

                mail_list_str = "\n".join(sorted(set(mail_list))) if mail_list else None

                stmt = (
                    update(tbl_code).where(tbl_code.c_code_file == entry.c_code_file).values(c_code_mail=mail_list_str)
                )
                database.db.session.execute(stmt)
                database.db.session.commit()
            else:
                logger.warning(msg=f"Not a file [{entry.c_code_file}]", extra={"job_id": job_id})

        logger.info(msg="Digging done", extra={"job_id": job_id})

    except Exception as e:
        logger.error(msg=f"Error extracting data:\n{e}", extra={"job_id": job_id}, exc_info=True)
        database.db.session.rollback()
