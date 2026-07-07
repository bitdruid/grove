import os
import io
import json
import re
import subprocess
import tempfile
import zipfile
from functools import lru_cache
from urllib.parse import urljoin
import magic
import img2pdf
import ocrmypdf
import pdftotext
from lxml import html
from PIL import Image, ImageOps
import easyocr

from grove.config import Config
from grove.extensions import logger


@lru_cache(maxsize=1)
def _valid_tlds() -> frozenset:
    """Load the bundled IANA TLD list (lowercased) once, for email validation."""
    try:
        with open(Config.TLDS, encoding="utf-8") as fh:
            return frozenset(l.strip().lower() for l in fh if l.strip() and not l.startswith("#"))
    except Exception as e:
        logger.error(msg=f"Could not load TLD list: {e}")
        return frozenset()

Image.MAX_IMAGE_PIXELS = 400000000


def cleanup_url(user_input, cut_path: bool = False):
    """Strip protocol and paths if exist."""
    if "://" in user_input:
        user_input = user_input.split("://")[1]
    if cut_path and "/" in user_input:
        user_input = user_input.split("/")[0]
    return user_input


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a string to be used as (part of) a filename.
    """
    disallowed = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]
    for char in disallowed:
        filename = filename.replace(char, ".")
    filename = ".".join(filter(None, filename.split(".")))
    return filename


def sanitize_url(url: str) -> str:
    """
    Sanitize a url by encoding special characters.
    """
    special_chars = [":", "*", "?", "&", "=", "<", ">", "\\", "|"]
    for char in special_chars:
        url = url.replace(char, f"%{ord(char):02x}")
    return url


def get_mime_type(file_path: str, job_id: str) -> str:
    """
    Get the MIME type of a file.
    Args:
        file_path (str): Path to the file.

    Returns:
        str: The MIME type of the file.
    """
    try:
        mime = magic.Magic(mime=True)
        return mime.from_file(file_path)
    except Exception as e:
        logger.warning(msg=f"Getting MIME type for {file_path}:\n{e}", extra={"job_id": job_id}, exc_info=False)
        return "application/octet-stream"


def img2a4pdf(img_path: str, job_id: str) -> str:
    """
    Converts an image to a PDF with A4 size and returns the path of the converted file.
    Args:
        img_path (str): The path of the image file to convert.

    Returns:
        str: The path of the converted PDF file.
    """
    try:

        def __split_image_to_a4(image_path, output_folder):
            img = Image.open(image_path)
            img_width, img_height = img.size

            # a4 aspect ratio calculation
            a4_aspect_ratio = 1.414
            max_img_height = img_width * a4_aspect_ratio
            last_img_height_cut = 0

            partial_images_paths = []

            while last_img_height_cut < img_height:
                # size of the partial image in pixels
                # max_img_height is the maximum height of the partial image to match A4 aspect ratio
                # last_img_height_cut is the height of the original image that has been cut so far
                crop_height = min(max_img_height, img_height - last_img_height_cut)
                partial_img = img.crop((0, last_img_height_cut, img_width, last_img_height_cut + crop_height))

                # if the last partial image is smaller than max_img_height, fill the rest with white
                if crop_height < max_img_height:
                    partial_img = ImageOps.expand(
                        partial_img, (0, 0, 0, int(max_img_height - crop_height)), fill="white"
                    )

                # save partial image
                partial_img_path = os.path.join(output_folder, f"partial_{len(partial_images_paths)}.jpeg")
                partial_img.save(partial_img_path)
                partial_images_paths.append(partial_img_path)

                last_img_height_cut += max_img_height

            img.close()

            return partial_images_paths

        def __images_to_pdf(image_paths, pdf_path):
            a4 = (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297))
            layout = img2pdf.get_layout_fun(a4)
            with open(pdf_path, "wb") as pdf_file:
                pdf_file.write(img2pdf.convert(image_paths, layout_fun=layout))
            for partial_img_path in image_paths:
                os.remove(partial_img_path)

        output_folder = os.path.dirname(img_path)
        pdf_path = os.path.join(output_folder, f"{os.path.basename(img_path).rsplit('.', 1)[0]}.pdf")
        partial_images_paths = __split_image_to_a4(img_path, output_folder)
        __images_to_pdf(partial_images_paths, pdf_path)
        if os.path.exists(pdf_path):
            return pdf_path
        return None

    except Exception as e:
        logger.error(msg=f"Error generating pdf for {img_path}:\n{e}", extra={"job_id": job_id}, exc_info=True)
        return None


def img2thumb(image_path: str, job_id: str, thumb_size: int = 54):
    """
    Creates a thumbnail image from the given image path and returns its path.
    The thumbnail is saved in the same directory as the original image with the extension ".thumb.jpeg".
    Args:
        image_path (str): Path to the original image file.

    Returns:
        str: Path to the thumbnail image file or None if an error occurred.
    """
    try:
        output_width = thumb_size
        if not image_path.endswith((".jpg", ".jpeg", ".png", ".gif", ".tiff", ".tif", ".bmp")):
            return
        img = Image.open(image_path)
        img_width, img_height = img.size
        img_aspect_ratio = img_width / img_height
        # If width > height use width as base to aspect ratio else height = width
        if img_width > img_height:
            output_height = int(output_width / img_aspect_ratio)
        else:
            img = img.crop((0, 0, img_width, img_width))
            output_height = output_width
        thumb_size = (output_width, output_height)
        thumb_path = f"{os.path.splitext(image_path)[0]}.thumb.jpeg"
        img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
        img.save(thumb_path)
        img.close()

        if os.path.exists(thumb_path):
            return thumb_path
        return None

    except Exception as e:
        logger.error(msg=f"Error generating thumbnail for {image_path}:\n{e}", extra={"job_id": job_id}, exc_info=True)
        return None


def ocr_image(ocr: easyocr.Reader, image_path: str, job_id: str) -> str:
    """
    Performs optical character recognition (OCR) on an image using EasyOCR and returns the extracted text.
    Args:
        ocr (easyocr.Reader): An instance of the EasyOCR Reader.
        image_path (str): The path to the image file.

    Returns:
        str: The extracted text from the image.
    """
    try:
        result = ocr.readtext(image_path)
        text = "\n".join([detection[1] for detection in result])
        return text.strip()
    except Exception as e:
        logger.error(msg=f"Error performing OCR on {image_path}:\n{e}", extra={"job_id": job_id}, exc_info=True)
        return ""


def ocr_pdf(pdf_path: str, job_id: str) -> str:
    """
    Performs OCR on the given PDF file and returns the extracted text as a single string.

    Args:
        pdf_path (str): Path to the PDF file to be processed.

    Returns:
        str: The extracted text content from the PDF.
    """
    try:
        stream = io.BytesIO()
        ocrmypdf.ocr(pdf_path, stream, language=["deu"], force_ocr=True)
        stream.seek(0)
        pdf = pdftotext.PDF(stream)
        content = " ".join(pdf).replace("\n", " ")
        return content.strip()

    except Exception as e:
        logger.error(msg=f"Error performing OCR on {pdf_path}:\n{e}", extra={"job_id": job_id}, exc_info=True)
        return ""


# exiftool -json tag keys that are filesystem bookkeeping, not embedded metadata.
_EXIF_NOISE_KEYS = frozenset(
    {
        "SourceFile",
        "ExifToolVersion",
        "FileName",
        "Directory",
        "FilePermissions",
        "FileModifyDate",
        "FileAccessDate",
        "FileInodeChangeDate",
    }
)


def _spaced_tag(key: str) -> str:
    """CamelCase exiftool key -> spaced name: GPSLatitude->GPS Latitude, MIMEType->MIME Type."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", key)


def exif_data(file_paths: list[str], job_id: str) -> dict[str, str]:
    """
    Extract embedded metadata from many files in a single exiftool invocation.

    exiftool reads any file type (images, PDFs, office docs, audio/video, and it
    even pulls author/description/OpenGraph tags out of HTML), so nothing is
    pre-filtered. Batching one process over all files avoids a per-file perl
    spawn, which matters on large crawls. Filesystem-only tags are dropped.

    Args:
        file_paths (list[str]): Files to inspect.
        job_id (str): The ID of the job (for logging).

    Returns:
        dict[str, str]: {absolute_path: "Tag: Value\\n..."} for every file that
        had embedded metadata. Empty dict if exiftool is unavailable or errors.
    """
    if not file_paths:
        return {}

    argfile = None
    try:
        # Argfile (one path per line): no shell-parsing of odd filenames, no ARG_MAX limit.
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
            tf.write("\n".join(file_paths))
            argfile = tf.name

        result = subprocess.run(
            ["exiftool", "-json", "-charset", "utf8", "-@", argfile],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if not result.stdout.strip():
            return {}

        out: dict[str, str] = {}
        for item in json.loads(result.stdout):
            src = item.get("SourceFile")
            if not src:
                continue
            lines = [f"{_spaced_tag(key)}: {value}" for key, value in item.items() if key not in _EXIF_NOISE_KEYS]
            text = "\n".join(lines).strip()
            if text:
                out[os.path.abspath(src)] = text
        return out

    except Exception as e:
        logger.error(msg=f"Error extracting EXIF (batch):\n{e}", extra={"job_id": job_id}, exc_info=True)
        return {}
    finally:
        if argfile and os.path.exists(argfile):
            os.unlink(argfile)


def extract_metatags(page_html: str, job_id: str) -> list[tuple]:
    """
    Extract all <meta>-tags from a given html-content and returns a list of unique items.

    Args:
        page_html (str): Content of a valid html-file.
        job_id (str): Job identifier.

    Returns:
        metatag_list (list): A list of tuples (tag, content) of all extracted metatags.
    """
    try:
        metatag_list = []
        tree = html.fromstring(page_html)
        metatags = tree.xpath("//meta")

        for tag in metatags:
            key = tag.get("name") or tag.get("property") or tag.get("http-equiv")
            content = tag.get("content")

            if key and content:
                metatag = f"{key}: {content}"
                metatag_list.append(metatag)

        metatag_list = list(set(metatag_list))
        if metatag_list:
            logger.debug(msg=f"Added [{len(metatag_list)}] metatags", extra={"job_id": job_id})
        return metatag_list

    except Exception as e:
        logger.error(msg=f"Error scraping metatags:\n{e}", extra={"job_id": job_id}, exc_info=True)


def extract_hyperlinks(page_html: str, job_id: str, base_url: str | None = None) -> list:
    """
    Extract href hyperlinks from a given html-content and returns a list of unique items.
    Relative hrefs are resolved against `base_url` (the page's original URL).

    Args:
        page_html (str): Content of a valid html-file.
        job_id (str): Job identifier.
        base_url (str): Original URL of the page; used to resolve relative hrefs.

    Returns:
        hyperlink_list (list): A list of all extracted href hyperlinks (host + path, no protocol).
    """
    try:
        hyperlink_list = []
        tree = html.fromstring(page_html)
        links = tree.xpath("//a/@href")

        for link in links:
            link = link.strip()
            if not link or link.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            if base_url and "://" not in link:
                link = urljoin(base_url, link)
            link = cleanup_url(link)
            hyperlink_list.append(link)

        hyperlink_list = list(set(hyperlink_list))
        if hyperlink_list:
            logger.debug(msg=f"Added [{len(hyperlink_list)}] hyperlinks", extra={"job_id": job_id})
        return hyperlink_list

    except Exception as e:
        logger.error(msg=f"Error scraping hyperlinks:\n{e}", extra={"job_id": job_id}, exc_info=True)


def extract_externals(page_html: str, job_id: str, skip_url: str) -> list:
    """
    Extract external links by regex from a given string and returns a list of unique items.

    Args:
        page_html (str): String where all containing urls/links should be extracted.
        job_id (str): Job identifier.
        skip_url (str): The source file's url to recognize internal links.

    Returns:
        external_list (list): A list of all extracted urls/links.
    """
    try:
        external_list = []
        links = re.findall(
            r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()!@:%_\+.~#?&//=]*)",
            page_html,
        )

        for link in links:
            if skip_url not in link:
                link = "".join(link)
                external_list.append(link)
        if external_list:
            logger.debug(msg=f"Added [{len(external_list)}] externals", extra={"job_id": job_id})
        return external_list

    except Exception as e:
        logger.error(msg=f"Error scraping external links:\n{e}", extra={"job_id": job_id}, exc_info=True)


def extract_mail(text_content: str, job_id: str) -> list:
    """
    Extract email addresses by regex from a given string and returns a list of unique items.

    Args:
        text_content (str): String where all containing urls/links should be extracted.
        job_id (str): Job identifier.

    Returns:
        mail_list (list): A list of all extracted mails.
    """
    # maybe add tld checking for valid mails
    try:
        mail_list = []
        obfuscated_at = r"[\[\(\{]\s{0,3}at\s{0,3}[\]\)\}]|&#64;|&#46;"
        text_content_deobfuscated = re.sub(obfuscated_at, "@", text_content, flags=re.M)
        mails_re = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"

        mails = re.findall(mails_re, text_content_deobfuscated)

        # drop hits whose final segment isn't a real IANA TLD (e.g. foo@2x.png)
        tlds = _valid_tlds()
        if tlds:
            mails = [m for m in mails if m.rsplit(".", 1)[-1].lower() in tlds]

        [mail_list.append(mail) for mail in mails]
        if mail_list:
            logger.debug(msg=f"Added [{len(mail_list)}] email addresses", extra={"job_id": job_id})
        return mail_list

    except Exception as e:
        logger.error(msg=f"Error scraping email addresses:\n{e}", extra={"job_id": job_id}, exc_info=True)


def zip_path(path: str) -> bool:
    try:
        logger.info(msg=f"Zipping [{path}]")
        zipname = os.path.basename(path) + ".zip"
        zippath = os.path.join(path, zipname)
        with zipfile.ZipFile(zippath, "w") as zf:
            for root, _, files in os.walk(path):
                for file in files:
                    filepath = os.path.join(root, file)
                    if filepath == zippath:
                        continue
                    arcpath = os.path.relpath(filepath, path)
                    # meta/ holds internal bookkeeping (search index, waybackup csv/db)
                    if arcpath == "meta" or arcpath.startswith("meta" + os.sep):
                        continue
                    zf.write(filename=filepath, arcname=arcpath)
        return zippath
    except Exception as e:
        logger.error(msg=f"Error zipping {path}:\n{e}", exc_info=True)
