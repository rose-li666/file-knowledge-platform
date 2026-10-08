"""Literal keyword normalization shared by SQLite and Python; no token splitting."""
import unicodedata


def search_key(value: str):
    return unicodedata.normalize("NFKC", value).casefold()
