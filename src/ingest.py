# src/ingest.py
from pathlib import Path
from typing import Dict

from .ingest_hwp import extract_hwp_text
from .ingest_pdf import extract_pdf_text


def _log_ok(stage: str, in_path: Path, out_path: Path) -> None:
    # 성공 로그(스펙): INGEST OK | <stage> | <input_path> -> <output_path>
    print(f"INGEST OK | {stage} | {in_path} -> {out_path}")


def _log_fail(stage: str, in_path: Path, exc: Exception) -> None:
    # 실패 로그(스펙): INGEST FAIL | <stage> | <input_path> | <error_type>: <message>
    print(f"INGEST FAIL | {stage} | {in_path} | {type(exc).__name__}: {exc}")


def save_text(text: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")


def ingest_one(path: Path, output_dir: Path = Path("data_text")) -> Path:
    suffix = path.suffix.lower()
    out_path = output_dir / f"{path.name}.txt"

    try:
        if suffix == ".pdf":
            text = extract_pdf_text(path)
        elif suffix == ".hwp":
            text = extract_hwp_text(path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")
        _log_ok("extract", path, out_path)
    except Exception as exc:
        _log_fail("extract", path, exc)
        raise

    try:
        save_text(text, out_path)
        _log_ok("write", path, out_path)
    except Exception as exc:
        _log_fail("write", path, exc)
        raise

    return out_path


def ingest_all(
    input_dir: Path = Path("data_raw"),
    output_dir: Path = Path("data_text"),
) -> Dict[str, int]:
    print(f"INGEST START | input={input_dir} | output={output_dir}")

    if not input_dir.exists():
        exc = FileNotFoundError(f"Input directory not found: {input_dir}")
        _log_fail("scan", input_dir, exc)
        raise exc

    files = [
        p
        for p in sorted(input_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in {".pdf", ".hwp"}
    ]

    summary = {"processed": 0, "succeeded": 0, "failed": 0}

    for path in files:
        summary["processed"] += 1
        try:
            # scan 단계는 "발견됨" 의미로 OK 로그를 남김
            _log_ok("scan", path, output_dir)
            ingest_one(path, output_dir=output_dir)
            summary["succeeded"] += 1
        except Exception:
            # 실패 상세 로그는 ingest_one 내부(extract/write)에서 이미 남김
            summary["failed"] += 1

    return summary


if __name__ == "__main__":
    ingest_all()
    print(ingest_all())
