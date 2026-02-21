from __future__ import annotations

from pathlib import Path

from .chunk_text import chunk_all
from .rich_chunk import chunk_rich


def chunk_plain(input_dir: Path, output_dir: Path, chunk_size: int = 900, overlap: int = 120) -> int:
    return chunk_all(input_dir=input_dir, output_dir=output_dir, chunk_size=chunk_size, overlap=overlap)


def chunk_markdown(input_dir: Path, output_dir: Path, chunk_size: int = 900, overlap: int = 120) -> int:
    return chunk_rich(input_dir=input_dir, output_dir=output_dir, chunk_size=chunk_size, overlap=overlap)
