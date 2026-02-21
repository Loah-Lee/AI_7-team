from __future__ import annotations

from pathlib import Path

from .ingest_hwp import extract_hwp_text
from .rich_pdf_extract import _convert_hwp_to_pdf


def load_hwp_text(path: Path) -> str:
    return extract_hwp_text(path)


def convert_hwp_to_pdf(hwp_path: Path, output_pdf: Path, timeout_s: int = 180) -> Path:
    return _convert_hwp_to_pdf(hwp_path, output_pdf, timeout_s=timeout_s)
