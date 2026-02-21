from __future__ import annotations

from pathlib import Path

from .ingest_pdf import extract_pdf_text


def load_pdf_text(path: Path) -> str:
    return extract_pdf_text(path)
