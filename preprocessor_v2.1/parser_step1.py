#!/usr/bin/env python3
"""
Parser Step 1: PDF → Markdown conversion for Korean RFP documents.

Two-pass, single-open architecture:
  Pass 1: Font profiling, cover title extraction, adaptive header clustering
  Pass 2: Markdown generation with table handling and reading-order merge

Output: Markdown with YAML frontmatter, max 2 header levels (# / ##).
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
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
    h1_range: Optional[tuple] = None   # (min_size, max_size)
    h2_range: Optional[tuple] = None
    document_title: str = ""
    total_pages: int = 0
    all_spans: list = field(default_factory=list)


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


def _is_sentence_ending(text: str) -> bool:
    """Short spans (≤15 chars) are numbered headers, not sentences — exempt from period count."""
    if len(text.strip()) <= 15:
        return False
    return bool(re.search(r'[.다요음임됨함니까]\s*$', text))


def _cluster_header_sizes(
    spans: List[SpanInfo], body_size: float, total_pages: int,
) -> Tuple[Optional[tuple], Optional[tuple]]:
    min_header_size = body_size + 2.0

    size_stats: Dict[float, Dict] = {}
    body_char_count = 0
    total_chars = 0

    for s in spans:
        sz = round(s.fontsize, 1)
        chars = len(s.text)
        total_chars += chars

        if sz == round(body_size, 1):
            body_char_count += chars

        if sz < min_header_size:
            continue

        if sz not in size_stats:
            size_stats[sz] = {
                "count": 0, "pages": set(), "char_count": 0,
                "span_lengths": [], "period_count": 0,
            }
        size_stats[sz]["count"] += 1
        size_stats[sz]["pages"].add(s.page_num)
        size_stats[sz]["char_count"] += chars
        size_stats[sz]["span_lengths"].append(chars)
        if _is_sentence_ending(s.text):
            size_stats[sz]["period_count"] += 1

    if not size_stats:
        return None, None

    reference_chars = max(body_char_count, total_chars * 0.5)

    # Phase 1: filter each fontsize INDIVIDUALLY (no pre-clustering)
    survivors: List[Tuple[float, Dict]] = []

    for sz in sorted(size_stats.keys(), reverse=True):
        stats = size_stats[sz]
        count = stats["count"]
        pages = stats["pages"]
        char_count = stats["char_count"]
        span_lengths = stats["span_lengths"]
        period_count = stats["period_count"]
        page_spread = len(pages)

        if count <= 5 and pages.issubset({0, 1}):
            continue
        if reference_chars > 0 and char_count > 0.15 * reference_chars:
            continue
        period_ratio = period_count / count if count > 0 else 0
        if period_ratio > 0.3:
            continue
        avg_span_len = sum(span_lengths) / len(span_lengths) if span_lengths else 0
        if avg_span_len > 80:
            continue
        if (total_pages > 0
                and page_spread > total_pages * 0.5
                and count > page_spread * 3):
            continue

        survivors.append((sz, stats))

    if not survivors:
        return None, None

    # Phase 2: merge adjacent survivors within ≤0.5pt (font rendering jitter only)
    groups: List[List[float]] = []
    for sz, _ in survivors:
        if groups and groups[-1][-1] - sz <= 0.5:
            groups[-1].append(sz)
        else:
            groups.append([sz])

    # Phase 3: pick top 2 groups → H1, H2
    ranked = []
    for group_sizes in groups:
        weighted_sum = sum(sz * size_stats[sz]["char_count"] for sz in group_sizes)
        weight_total = sum(size_stats[sz]["char_count"] for sz in group_sizes)
        rep = weighted_sum / weight_total if weight_total > 0 else group_sizes[0]
        ranked.append((rep, min(group_sizes), max(group_sizes)))

    h1_range = (ranked[0][1], ranked[0][2]) if len(ranked) >= 1 else None
    h2_range = (ranked[1][1], ranked[1][2]) if len(ranked) >= 2 else None

    return h1_range, h2_range


def _maybe_swap_h1_h2(
    h1_range: Optional[tuple],
    h2_range: Optional[tuple],
    spans: List[SpanInfo],
) -> Tuple[Optional[tuple], Optional[tuple]]:
    """
    H1/H2 계층 역전 방지. 스왑 조건:
      - H1 빈도 ≤ 2 AND H1/(H1+H2) < 10% AND H2 빈도 존재
      - 스왑 후보 H1이 물리적 페이지 0~1에만 존재할 때만 실행
    """
    if not h1_range or not h2_range:
        return h1_range, h2_range

    h1_spans = [s for s in spans if h1_range[0] <= round(s.fontsize, 1) <= h1_range[1]]
    h2_spans = [s for s in spans if h2_range[0] <= round(s.fontsize, 1) <= h2_range[1]]
    h1_count = len(h1_spans)
    h2_count = len(h2_spans)
    total = h1_count + h2_count

    if total == 0 or h2_count == 0:
        return h1_range, h2_range

    if (h1_count <= 2
            and h1_count / total < 0.10
            and all(s.page_num <= 1 for s in h1_spans)):
        return h2_range, h1_range

    return h1_range, h2_range


def _build_font_profile(doc: fitz.Document) -> FontProfile:
    spans = _collect_spans(doc)
    body_size = _compute_body_size(spans)
    document_title = _extract_cover_title(spans)
    h1_range, h2_range = _cluster_header_sizes(spans, body_size, len(doc))
    h1_range, h2_range = _maybe_swap_h1_h2(h1_range, h2_range, spans)

    return FontProfile(
        body_size=body_size,
        h1_range=h1_range,
        h2_range=h2_range,
        document_title=document_title,
        total_pages=len(doc),
        all_spans=spans,
    )


# ---------------------------------------------------------------------------
# Pass 2 — Markdown generation
# ---------------------------------------------------------------------------

def _classify_header(fontsize: float, profile: FontProfile) -> Optional[str]:
    """Classify a fontsize as H1, H2, or None."""
    sz = round(fontsize, 1)

    # Sizes at or above H1 min get H1
    if profile.h1_range:
        if sz >= profile.h1_range[0]:
            return "#"

    if profile.h2_range:
        if profile.h2_range[0] <= sz <= profile.h2_range[1]:
            return "##"

    return None


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
    profile: FontProfile,
) -> str:
    """Generate markdown for a single page."""
    lines: List[str] = []
    lines.append(f"[[PAGE:{page_num + 1}]]")

    # --- Tables ---
    tables_result = cast(Any, page).find_tables()
    table_rects: List[fitz.Rect] = []
    table_entries: List[Tuple[float, str]] = []  # (y_position, markdown)

    for table in tables_result.tables:
        table_rect = fitz.Rect(table.bbox)
        table_rects.append(table_rect)

        if _is_toc_table(page, table):
            continue  # skip TOC tables

        try:
            df = table.to_pandas()
            if df.empty:
                continue
            table_md = df.to_markdown(index=False)
            if table_md:
                table_entries.append((table_rect.y0, "\n" + table_md + "\n"))
        except Exception as e:
            print(f"⚠️ Table conversion error on page {page_num + 1}: {e}")

    # --- Text spans (excluding table areas) ---
    # Store (y, x, raw_text, fontsize) — header prefix applied AFTER line merge
    text_entries: List[Tuple[float, float, str, float]] = []
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

                fontsize = round(span.get("size", 0), 2)

                if _rect_intersects_any(bbox, table_rects):
                    if not _classify_header(fontsize, profile):
                        continue

                text = fix_korean_spacing(text)

                y = bbox[1]
                x = bbox[0]
                text_entries.append((y, x, text, fontsize))

    text_entries.sort(key=lambda t: (t[0], t[1]))

    # --- Merge spans on same line, then classify header by max fontsize ---
    merged_elements: List[Tuple[float, str]] = []
    Y_TOLERANCE = 3.0

    if text_entries:
        current_y = text_entries[0][0]
        current_line_parts: List[str] = []
        current_max_fontsize = 0.0

        for y, x, text, fontsize in text_entries:
            if abs(y - current_y) > Y_TOLERANCE:
                line_text = " ".join(current_line_parts)
                header_prefix = _classify_header(current_max_fontsize, profile)
                if header_prefix:
                    line_text = f"{header_prefix} {line_text}"
                merged_elements.append((current_y, line_text))
                current_line_parts = [text]
                current_max_fontsize = fontsize
                current_y = y
            else:
                current_line_parts.append(text)
                current_max_fontsize = max(current_max_fontsize, fontsize)

        if current_line_parts:
            line_text = " ".join(current_line_parts)
            header_prefix = _classify_header(current_max_fontsize, profile)
            if header_prefix:
                line_text = f"{header_prefix} {line_text}"
            merged_elements.append((current_y, line_text))

    # Add table entries
    for y, table_md in table_entries:
        merged_elements.append((y, table_md))

    # Sort all elements by y position
    merged_elements.sort(key=lambda t: t[0])

    # Build page output
    for _, text in merged_elements:
        is_header = text.startswith("# ") or text.startswith("## ")
        # Add blank line before headers for readability
        if is_header and lines and lines[-1].strip():
            lines.append("")
        lines.append(text)
        if is_header:
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def parse_pdf_to_markdown(pdf_path: str, output_path: str) -> None:
    """Parse a PDF to markdown with adaptive font profiling."""
    print(f"📄 Parsing: {pdf_path}")

    doc = fitz.open(pdf_path)
    try:
        # === Pass 1: Font profiling ===
        profile = _build_font_profile(doc)

        print(f"   body_size={profile.body_size}, "
              f"h1={profile.h1_range}, h2={profile.h2_range}")
        if len(profile.document_title) > 60:
            print(f"   title=\"{profile.document_title[:60]}...\"")
        else:
            print(f"   title=\"{profile.document_title}\"")

        # === Pass 2: Markdown generation ===
        page_markdowns: List[str] = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_md = _generate_page_markdown(page, page_num, profile)
            page_markdowns.append(page_md)

        body = "\n\n".join(page_markdowns)

        # === YAML frontmatter ===
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

        # === Write output ===
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(full_md, encoding='utf-8')

        # Stats
        h1_count = full_md.count("\n# ")
        h2_count = full_md.count("\n## ")
        print(f"✅ Done: {output_path} "
              f"({len(full_md):,} chars, H1={h1_count}, H2={h2_count})")

    finally:
        doc.close()


if __name__ == '__main__':
    pdf_dir = Path('output/temp_pdf')
    output_dir = Path('output')
    output_dir.mkdir(exist_ok=True)
    for pdf_file in sorted(pdf_dir.glob('*.pdf')):
        output_path = output_dir / f'step1_parsed_{pdf_file.stem}.md'
        parse_pdf_to_markdown(str(pdf_file), str(output_path))
