import pathlib


class Config:
    BASE_DIR = pathlib.Path(__file__).resolve().parent
    MISC_DIR = BASE_DIR / "misc"
    SOURCES = MISC_DIR / "sources.csv"
    TLDS = MISC_DIR / "tlds-alpha-by-domain.txt"  # IANA snapshot for email TLD validation
