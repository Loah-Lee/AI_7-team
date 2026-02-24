#!/usr/bin/env python3
"""
Parser Step 1: PDF → Markdown conversion for Korean RFP documents (v3).

Two-pass, single-open architecture:
  Pass 1: Font profiling, cover title extraction
  Pass 2: Markdown generation with table handling and reading-order merge

Output: Markdown with YAML frontmatter, [[PAGE:N]] markers, NO header insertion.
Header detection is deferred to the chunker (regex-based hierarchy extraction).
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Optional, List, Dict, Tuple, cast
from collections import Counter

import fitz  # PyMuPDF
import pandas as pd


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SpanInfo:
    fontsize: float
    text: str
    page_num: int
    is_bold: bool
    bbox: tuple


@dataclass
class FontProfile:
    body_size: float
    document_title: str = ""
    total_pages: int = 0


# ---------------------------------------------------------------------------
# Korean spacing fix (minimal)
# ---------------------------------------------------------------------------

def fix_korean_spacing(text: str) -> str:
    """Fix single-char-repeated Korean spacing artifacts."""
    return re.sub(
        r'(?<![가-힣])([가-힣]) ([가-힣](?:(?: [가-힣])){1,})(?![가-힣])',
        lambda m: m.group(0).replace(' ', ''),
        text,
    )


# ---------------------------------------------------------------------------
# Pass 1 — Font profiling
# ---------------------------------------------------------------------------

def _collect_spans(doc: fitz.Document) -> List[SpanInfo]:
    """Collect every text span from all pages."""
    spans = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        page_dict: Dict[str, Any] = cast(Dict[str, Any], page.get_text("dict"))
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:

                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    fontsize = round(span.get("size", 0), 2)
                    flags = span.get("flags", 0)
                    is_bold = bool(flags & (1 << 4))
                    bbox = span.get("bbox", (0, 0, 0, 0))
                    spans.append(SpanInfo(
                        fontsize=fontsize,
                        text=text,
                        page_num=page_num,
                        is_bold=is_bold,
                        bbox=bbox,
                    ))
    return spans


def _compute_body_size(spans: List[SpanInfo]) -> float:
    """Body size = mode of all fontsizes, weighted by character count."""
    char_counts: Counter = Counter()
    for s in spans:
        char_counts[round(s.fontsize, 1)] += len(s.text)
    if not char_counts:
        return 10.0
    return char_counts.most_common(1)[0][0]


def _extract_cover_title(spans: List[SpanInfo]) -> str:
    """Extract document title from page 0 using largest fontsize heuristic."""
    page0 = [s for s in spans if s.page_num == 0]
    if not page0:
        return ""

    size_groups: Dict[float, List[SpanInfo]] = {}
    for s in page0:
        key = round(s.fontsize, 1)
        size_groups.setdefault(key, []).append(s)

    sorted_sizes = sorted(size_groups.keys(), reverse=True)

    for size in sorted_sizes:
        group = size_groups[size]
        combined = " ".join(s.text for s in group).strip()
        if len(combined) < 3 or len(combined) > 150:
            continue
        if re.match(r'^\d{4}[\.\s]', combined):
            continue
        return _clean_title(combined)

    for size in sorted_sizes:
        group = size_groups[size]
        combined = " ".join(s.text for s in group).strip()
        if len(combined) >= 3:
            return _clean_title(combined)

    return ""


def _clean_title(raw: str) -> str:
    title = re.sub(r'^[-–—]\s*', '', raw).strip()
    title = fix_korean_spacing(title)
    words = title.split()
    mid = len(words) // 2
    if mid > 0 and words[:mid] == words[mid:2 * mid]:
        title = " ".join(words[:mid] + words[2 * mid:])
    return title


def _build_font_profile(doc: fitz.Document) -> FontProfile:
    spans = _collect_spans(doc)
    body_size = _compute_body_size(spans)
    document_title = _extract_cover_title(spans)

    return FontProfile(
        body_size=body_size,
        document_title=document_title,
        total_pages=len(doc),
    )


# ---------------------------------------------------------------------------
# Pass 2 — Markdown generation (no header insertion)
# ---------------------------------------------------------------------------

def _is_toc_table(page: fitz.Page, table) -> bool:
    """Detect TOC tables by page content or cell patterns."""
    page_text = page.get_text("text")
    if "목차" in page_text:
        return True

    toc_pattern = re.compile(r'[·.…\-]{3,}\s*\d+')
    try:
        df = table.to_pandas()
        for col in df.columns:
            for val in df[col].astype(str):
                if toc_pattern.search(val):
                    return True
    except Exception:
        pass

    return False


def _rect_intersects_any(
    span_bbox: tuple, table_rects: List[fitz.Rect],
) -> bool:
    """Check if a span bbox intersects any table rect."""
    span_rect = fitz.Rect(span_bbox)
    for tr in table_rects:
        if span_rect.intersects(tr):
            return True
    return False


def _generate_page_markdown(
    page: fitz.Page,
    page_num: int,
) -> str:
    lines: List[str] = []
    lines.append(f"<<PAGE: {page_num + 1}>>")

    tables_result = cast(Any, page).find_tables()
    table_rects: List[fitz.Rect] = []
    table_entries: List[Tuple[float, str]] = []

    for table in tables_result.tables:
        table_rect = fitz.Rect(table.bbox)
        table_rects.append(table_rect)

        if _is_toc_table(page, table):
            continue

        try:
            df = table.to_pandas()
            if df.empty:
                continue
            table_md = df.to_markdown(index=False)
            if table_md:
                table_entries.append((table_rect.y0, "\n" + table_md + "\n"))
        except Exception as e:
            print(f"⚠️ Table conversion error on page {page_num + 1}: {e}")

    text_entries: List[Tuple[float, float, str]] = []
    page_dict: Dict[str, Any] = cast(Dict[str, Any], page.get_text("dict"))

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line_info in block.get("lines", []):
            for span in line_info.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue

                bbox = tuple(span.get("bbox", (0, 0, 0, 0)))

                if _rect_intersects_any(bbox, table_rects):
                    continue

                text = fix_korean_spacing(text)
                text_entries.append((bbox[1], bbox[0], text))

    text_entries.sort(key=lambda t: (t[0], t[1]))

    merged_elements: List[Tuple[float, str]] = []
    Y_TOLERANCE = 3.0

    if text_entries:
        current_y = text_entries[0][0]
        current_line_parts: List[str] = []

        for y, x, text in text_entries:
            if abs(y - current_y) > Y_TOLERANCE:
                merged_elements.append((current_y, " ".join(current_line_parts)))
                current_line_parts = [text]
                current_y = y
            else:
                current_line_parts.append(text)

        if current_line_parts:
            merged_elements.append((current_y, " ".join(current_line_parts)))

    for y, table_md in table_entries:
        merged_elements.append((y, table_md))

    merged_elements.sort(key=lambda t: t[0])

    for _, text in merged_elements:
        lines.append(text)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def parse_pdf_to_markdown(pdf_path: str, output_path: str) -> None:
    print(f"📄 Parsing: {pdf_path}")

    doc = fitz.open(pdf_path)
    try:
        profile = _build_font_profile(doc)

        print(f"   body_size={profile.body_size}")
        if len(profile.document_title) > 60:
            print(f"   title=\"{profile.document_title[:60]}...\"")
        else:
            print(f"   title=\"{profile.document_title}\"")

        page_markdowns: List[str] = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_md = _generate_page_markdown(page, page_num)
            page_markdowns.append(page_md)

        body = "\n\n".join(page_markdowns)

        source_file = Path(pdf_path).name
        parsed_at = datetime.now().isoformat()
        frontmatter = (
            "---\n"
            f"document_title: \"{profile.document_title}\"\n"
            f"source_file: \"{source_file}\"\n"
            f"total_pages: {profile.total_pages}\n"
            f"parsed_at: \"{parsed_at}\"\n"
            "---\n"
        )

        full_md = frontmatter + "\n" + body

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(full_md, encoding='utf-8')

        print(f"✅ Done: {output_path} ({len(full_md):,} chars)")

    finally:
        doc.close()


if __name__ == '__main__':
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    pdf_dir = PROJECT_ROOT / 'output' / 'temp_pdf'
    output_dir = PROJECT_ROOT / 'output'
    output_dir.mkdir(exist_ok=True)
    for pdf_file in sorted(pdf_dir.glob('*.pdf')):
        output_path = output_dir / f'step1_parsed_{pdf_file.stem}.md'
        parse_pdf_to_markdown(str(pdf_file), str(output_path))
