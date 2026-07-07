"""
Full-text search over downloaded job files (Whoosh).

One index per job under ``instance/index/<job_id>/`` so deletion is a clean
``rmtree`` (no tombstones) and concurrent jobs index in parallel without a
shared writer lock. Content is **unstored** — the index holds only tokens, never
a copy of the files (jobs can be tens of GB); snippets are produced by re-reading
the matched file at query time. Large files are split into fixed-size chunks
(several index docs pointing at the same on-disk file), so nothing is truncated
and the indexer never holds more than one chunk of text in memory.

Global search opens every per-job index and searches them together via a
``MultiReader``; results collapse back to one row per file.
"""

from __future__ import annotations

import glob
import os
import shutil

from whoosh import index as windex
from whoosh.analysis import LowercaseFilter, RegexTokenizer
from whoosh.fields import ID, NUMERIC, Schema, TEXT
from whoosh.highlight import ContextFragmenter, HtmlFormatter
from whoosh.qparser import QueryParser
from whoosh.reading import MultiReader
from whoosh.searching import Searcher

from grove.db import database, select, tbl_code
from grove.extensions import logger
from grove.services.tools.tool import Tool


JOBS_ROOT = "jobs"
INDEX_GLOB = os.path.join(JOBS_ROOT, "*", "meta", "index")
CHUNK_CHARS = 2 * 1024 * 1024  # ~2 MiB of text per index document
SAMPLE_BYTES = 8192  # bytes inspected by the binary sniff
NONTEXT_RATIO = 0.30  # >30% non-text bytes ⇒ treat as binary
SKIP_MIME_PREFIXES = ("image/", "video/", "audio/", "font/")
SKIP_MIME_EXACT = ("application/pdf", "application/zip", "application/gzip", "application/x-gzip")

_TEXT_BYTES = set(bytes(range(32, 127)) + b"\n\r\t\f\b")

# keep internal "@" so an email stays one token (test@hans.de), findable via *@*
# leading "@" is still dropped - "@media"/"@handle" searches are unchanged
# no stemming to keep mails/domains searchable
_TOKEN_EXPR = r"\w+([.@]?\w+)*"
_ANALYZER = RegexTokenizer(expression=_TOKEN_EXPR) | LowercaseFilter()


# index location


def _job_index_dir(job_id: str) -> str:
    # index lives under the job dir in meta/ (excluded from zip) - is removed when job dir is
    return os.path.join(JOBS_ROOT, job_id, "meta", "index")


def _schema() -> Schema:
    return Schema(
        job=ID(stored=True),
        path=ID(stored=True),
        chunk=NUMERIC(stored=True),  # chunk ordinal within the file
        content=TEXT(stored=False, analyzer=_ANALYZER),  # unstored: never duplicated
    )


# text detection


def _is_binary_mime(mime: str | None) -> bool:
    if not mime:
        return False
    return mime.startswith(SKIP_MIME_PREFIXES) or mime in SKIP_MIME_EXACT


def _looks_like_text(path: str) -> bool:
    """Sniff bytes (git/ripgrep style): NUL byte or too many control bytes ⇒ binary."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(SAMPLE_BYTES)
    except OSError:
        return False
    if not chunk or b"\x00" in chunk:
        return False
    nontext = sum(b not in _TEXT_BYTES for b in chunk)
    return nontext / len(chunk) <= NONTEXT_RATIO


def _iter_chunks(path: str):
    """Yield (ordinal, text) chunks, never holding more than CHUNK_CHARS in memory."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        ordinal = 0
        while True:
            data = f.read(CHUNK_CHARS)
            if not data:
                break
            yield ordinal, data
            ordinal += 1


def _read_chunk(path: str, ordinal: int) -> str:
    """Re-read a single chunk's text (for highlighting a matched result)."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for _ in range(ordinal):
                if not f.read(CHUNK_CHARS):
                    return ""
            return f.read(CHUNK_CHARS)
    except OSError:
        return ""


# indexer (pipeline tool)


class SearchIndex(Tool):
    """Builds the per-job Whoosh index from the job's tbl_code file rows."""

    name = "search_index"

    def db_read(self, job_id: str, **kwargs):
        stmt = select(tbl_code.c_code_file, tbl_code.c_code_mime).where(tbl_code.job_id == job_id)
        return database.db.session.execute(stmt).all()

    def run(self, job_id: str, data, **kwargs) -> int:
        rows = data or []
        idx_dir = _job_index_dir(job_id)
        if os.path.isdir(idx_dir):
            shutil.rmtree(idx_dir, ignore_errors=True)
        os.makedirs(idx_dir, exist_ok=True)

        ix = windex.create_in(idx_dir, _schema())
        writer = ix.writer()
        indexed = 0
        seen: set[str] = set()
        for code_file, code_mime in rows:
            if not code_file or code_file in seen:
                continue
            seen.add(code_file)
            if _is_binary_mime(code_mime) or not os.path.isfile(code_file):
                continue
            if not _looks_like_text(code_file):
                continue
            try:
                for ordinal, chunk in _iter_chunks(code_file):
                    writer.add_document(job=job_id, path=code_file, chunk=ordinal, content=chunk)
                indexed += 1
            except OSError as e:
                logger.warning(msg=f"Skipped unreadable file [{code_file}]: {e}", extra={"job_id": job_id})
        writer.commit()
        logger.info(msg=f"Search index built [{indexed}] text files", extra={"job_id": job_id})
        return indexed


search_index = SearchIndex()


# lifecycle


def drop_job(job_id: str) -> None:
    """Remove a job's index (called from del_job)."""
    shutil.rmtree(_job_index_dir(job_id), ignore_errors=True)


def drop_all() -> None:
    """Remove every per-job index (called from prune_app)."""
    for d in glob.glob(INDEX_GLOB):
        shutil.rmtree(d, ignore_errors=True)


# querying


def search_all(query_str: str, limit: int = 100) -> list[dict]:
    """
    Search every per-job index together and return one result per file:
        {job, path, snippet}  — snippet is HTML with <mark> around the matches.
    """
    if not query_str or not query_str.strip():
        return []

    readers = []
    for d in sorted(glob.glob(INDEX_GLOB)):
        if windex.exists_in(d):
            try:
                readers.append(windex.open_dir(d).reader())
            except Exception as e:  # corrupt/locked index shouldn't break global search
                logger.warning(msg=f"Skipped unreadable index [{d}]: {e}")
    if not readers:
        return []

    reader = readers[0] if len(readers) == 1 else MultiReader(readers)
    searcher = Searcher(reader)
    try:
        query = QueryParser("content", schema=_schema()).parse(query_str)
        hits = searcher.search(query, limit=None, terms=True)
        hits.fragmenter = ContextFragmenter(maxchars=240, surround=60)
        hits.formatter = HtmlFormatter(tagname="mark", classname="", termclass="")

        out: list[dict] = []
        seen: set[str] = set()
        for hit in hits:
            path = hit["path"]
            if path in seen:
                continue
            seen.add(path)
            snippet = hit.highlights("content", text=_read_chunk(path, hit["chunk"]), top=2)
            if not snippet:
                snippet = _read_chunk(path, hit["chunk"])[:240]
            out.append({"job": hit["job"], "path": path, "snippet": snippet})
            if len(out) >= limit:
                break
        return out
    finally:
        searcher.close()
