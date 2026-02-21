from __future__ import annotations

import hashlib
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


_TOC_RE = re.compile(r"목\s*차")
_SECTION_RE = re.compile(
    r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?|제?\s*\d+\s*(장|절|항)\b|\d+[.)]\s+)"
)
_TOC_ITEM_RE = re.compile(
    r"^\s*(?:[0-9]+[.)]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.)\s+.+(?:[-·\.]{3,}\s*\d+|\s+\d+)$"
)
_MD_HEADER_RE = re.compile(r"^\s*#{1,6}\s+")


def _split_toc_block(text: str) -> tuple[str | None, str]:
    lines = text.splitlines()
    toc_lines: List[str] = []
    rest_lines: List[str] = []
    in_toc = False
    for line in lines:
        norm = line.replace("\u00a0", " ")
        if not in_toc and _TOC_RE.search(norm):
            in_toc = True
            toc_lines.append("목차")
            continue
        if in_toc:
            if _TOC_ITEM_RE.match(norm):
                toc_lines.append(line)
                continue
            if _MD_HEADER_RE.match(norm) or _SECTION_RE.match(norm):
                in_toc = False
                rest_lines.append(line)
                continue
            toc_lines.append(line)
            continue
        rest_lines.append(line)
    toc = "\n".join(toc_lines).strip() if toc_lines else None
    rest = "\n".join(rest_lines).strip()
    return toc, rest


_LIST_ITEM_RE = re.compile(
    r"^\s*(?:[-*•○●■·]|[0-9]+[.)]|[가-하]\.)\s+"
)


def _separate_list_items(text: str) -> str:
    lines = text.splitlines()
    out: List[str] = []
    for line in lines:
        if _LIST_ITEM_RE.match(line):
            if out and out[-1].strip():
                out.append("")
        out.append(line)
    return "\n".join(out)


def _split_by_sections(text: str) -> List[str]:
    lines = text.splitlines()
    sections: List[str] = []
    buf: List[str] = []
    for line in lines:
        norm = line.replace("\u00a0", " ")
        if _MD_HEADER_RE.match(norm) or _SECTION_RE.match(norm):
            if buf:
                sections.append("\n".join(buf).strip())
                buf = []
        buf.append(line)
    if buf:
        sections.append("\n".join(buf).strip())
    return [s for s in sections if s]


def _pack_paragraphs(text: str, chunk_size: int, overlap: int) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buf = ""
    for para in paras:
        if len(para) > chunk_size:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            chunks.extend(_chunk_text(para, chunk_size, overlap))
            continue
        if not buf:
            buf = para
            continue
        if len(buf) + 2 + len(para) <= chunk_size:
            buf = f"{buf}\n\n{para}"
        else:
            chunks.append(buf.strip())
            if overlap > 0 and chunks[-1]:
                tail = chunks[-1][-overlap:]
                buf = f"{tail}\n\n{para}"
            else:
                buf = para
    if buf:
        chunks.append(buf.strip())
    return chunks


def _chunk_by_structure(text: str, chunk_size: int, overlap: int) -> List[str]:
    text = _separate_list_items(text)
    toc, rest = _split_toc_block(text)
    body = rest or text

    sections = _split_by_sections(body)
    if toc:
        if sections:
            sections[0] = f"{toc}\n\n{sections[0]}".strip()
        else:
            sections = [toc]

    chunks: List[str] = []
    for section in sections:
        if len(section) <= chunk_size:
            chunks.append(section)
            continue
        chunks.extend(_pack_paragraphs(section, chunk_size, overlap))

    return [c for c in chunks if c]


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


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _chunk_id(text: str) -> str:
    normalized = _normalize_text(text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _extract_section_title(chunk: str) -> str:
    for line in chunk.splitlines():
        norm = line.replace("\u00a0", " ")
        if _MD_HEADER_RE.match(norm) or _SECTION_RE.match(norm):
            return norm.strip()
    return ""


def _extract_page_refs(assets: List[str]) -> List[int]:
    pages: List[int] = []
    for asset in assets:
        name = Path(asset).name
        match = re.search(r"p(\d+)_", name)
        if match:
            pages.append(int(match.group(1)))
    return sorted(set(pages))


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
            chunks = _chunk_by_structure(text, chunk_size=chunk_size, overlap=overlap)

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
                    assets = _extract_assets(chunk)
                    metadata = {
                        "doc_id": rel_path.stem,
                        "section_title": _extract_section_title(chunk),
                        "page_refs": _extract_page_refs(assets),
                    }
                    if assets:
                        metadata["assets"] = assets
                    record["metadata"] = metadata
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

            _log_ok("chunk", path, out_path)
        except Exception as exc:
            _log_fail("chunk", path, exc)
            continue


if __name__ == "__main__":
    chunk_rich()
