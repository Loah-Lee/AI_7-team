# NOTE:
# Global metadata CSV exists at project-level.
# source_path can be used later as a join key.

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable, List


def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: List[str] = []
    start = 0
    step = chunk_size - overlap
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def _iter_text_files(input_dir: Path) -> Iterable[Path]:
    return (
        p
        for p in sorted(input_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() == ".txt"
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _chunk_id(text: str) -> str:
    normalized = _normalize_text(text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def chunk_all(
    input_dir: Path = Path("data_text"),
    output_dir: Path = Path("data_chunks"),
    *,
    chunk_size: int = 1000,
    overlap: int = 100,
) -> None:
    print(f"INGEST START | input={input_dir} | output={output_dir}")

    if not input_dir.exists():
        exc = FileNotFoundError(f"Input directory not found: {input_dir}")
        print(f"INGEST FAIL | chunk | {input_dir} | {type(exc).__name__}: {exc}")
        raise exc

    for path in _iter_text_files(input_dir):
        rel_path = path.relative_to(input_dir)
        out_path = output_dir / rel_path
        out_path = out_path.with_suffix(out_path.suffix + ".jsonl")

        try:
            text = path.read_text(encoding="utf-8")
            chunks = _chunk_text(text, chunk_size=chunk_size, overlap=overlap)

            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", encoding="utf-8") as f:
                for idx, chunk in enumerate(chunks):
                    record = {
                        "id": f"{rel_path.as_posix()}#{idx}",
                        "source_path": rel_path.as_posix(),
                        "chunk_index": idx,
                        "chunk_id": _chunk_id(chunk),
                        "text": chunk,
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

            print(f"INGEST OK | chunk | {path} -> {out_path}")
        except Exception as exc:
            print(f"INGEST FAIL | chunk | {path} | {type(exc).__name__}: {exc}")
            continue


if __name__ == "__main__":
    chunk_all()
