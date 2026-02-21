from pathlib import Path


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            "pypdf is required for PDF extraction. Install with: pip install pypdf"
        ) from exc

    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        parts.append(text)
    return "\n".join(parts).strip()
