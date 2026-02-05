from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List


def _log_start(input_path: Path, output_path: Path) -> None:
    print(f"INGEST START | input={input_path} | output={output_path}")


def _log_ok(stage: str, input_path: Path, output_path: Path) -> None:
    print(f"INGEST OK | {stage} | {input_path} -> {output_path}")


def _log_fail(stage: str, input_path: Path, exc: Exception) -> None:
    print(f"INGEST FAIL | {stage} | {input_path} | {type(exc).__name__}: {exc}")


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


def _iter_md_files(input_dir: Path) -> Iterable[Path]:
    return (
        p
        for p in sorted(input_dir.rglob("*.md"))
        if p.is_file() and not p.name.endswith(".manifest.json")
    )


def _extract_assets(text: str) -> List[str]:
    assets = []
    for match in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
        if "data_assets" in match:
            assets.append(match)
    return assets


def chunk_rich(
    input_dir: Path = Path("notebooks") / "data_rich",
    output_dir: Path = Path("notebooks") / "data_chunks_rich",
    *,
    chunk_size: int = 1000,
    overlap: int = 100,
) -> None:
    _log_start(input_dir, output_dir)

    if not input_dir.exists():
        exc = FileNotFoundError(f"Input directory not found: {input_dir}")
        _log_fail("chunk", input_dir, exc)
        raise exc

    for path in _iter_md_files(input_dir):
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
                        "text": chunk,
                    }
                    assets = _extract_assets(chunk)
                    if assets:
                        record["metadata"] = {"assets": assets}
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

            _log_ok("chunk", path, out_path)
        except Exception as exc:
            _log_fail("chunk", path, exc)
            continue


if __name__ == "__main__":
    chunk_rich()
