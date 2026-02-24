#!/usr/bin/env python3
"""
Chunker Step 4: 6-Step Document Processing Pipeline (v3.1)
Input: output/step2_audited_{stem}.md (fallback: step1_parsed_{stem}.md)
Output: output/chunks/chunk_{NNNNN}.json
Pipeline (Steps 2–6):
  2. Table flattening  →  flatten_tables_in_text()
  3. Regex section hierarchy extraction
  4. Header insertion (# level 1, ## level 2)
  5. Page marker conversion  [[PAGE:N]] → [[[Page: N]]]
  6. Section map + RecursiveCharacterTextSplitter
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime

from langchain_text_splitters import RecursiveCharacterTextSplitter

from .table_flattener import flatten_tables_in_text
from .text_cleaner import (
    _BULLET_RE,
    _BACKTICK_BULLET_RE,
    _BOLD_RE,
    _HEADER_FOOTER_PATTERNS,
    _MULTI_BLANK_RE,
    _TRAILING_WS_RE,
)

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_PAGE_MARKER_OLD_RE = re.compile(r'<<PAGE:\s*(\d+)>>')
_PAGE_MARKER_NEW_RE = re.compile(r'\[\[\[Page:\s*(\d+)\]\]\]')

# Group A: 제N편/장/절/조/항
_LEGAL_RE = re.compile(r"^(제\s*\d+\s*[장절조편항][\s.:]\s*.+)$", re.MULTILINE)
_LEGAL_TYPE_RE = re.compile(r"제\s*\d+\s*([장절조편항])")

# Group B: 숫자 (depth 3 → 2 → 1 순서로 검사)
_NUMBERED_D3_RE = re.compile(
    r"^(\d+\.\d+\.\d+(?:\.\d+)*\.?\s+\S.+)$", re.MULTILINE,
)
_NUMBERED_D2_RE = re.compile(r"^(\d+\.\d+\.?\s+\S.+)$", re.MULTILINE)
_NUMBERED_D1_RE = re.compile(r"^(\d{1,2}\.\s+\S.+)$", re.MULTILINE)

# Group B: 로마 숫자 (ASCII + Unicode)
_ROMAN_RE = re.compile(
    r"^([IVXivxⅠ-Ⅻⅰ-ⅻ]+\.\s+\S.+)$", re.MULTILINE,
)

# Group B: 한국어 글자 말머리 (가~하)
_KOREAN_LETTER_RE = re.compile(r"^([가-하]\.\s+\S.+)$", re.MULTILINE)

# Group B: 괄호 말머리
_BRACKET_RE = re.compile(r"^(\[.+\]\s*.*)$", re.MULTILINE)

# Group A 법적 순서
LEGAL_ORDER = ["편", "장", "절", "조", "항"]


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> Tuple[Dict, str]:
    meta: Dict[str, str] = {}
    body = text

    yaml_match = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if yaml_match:
        yaml_content = yaml_match.group(1)
        body = text[yaml_match.end():]
        for line in yaml_content.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                meta[key.strip()] = value.strip().strip('"\'')

    return meta, body


# ---------------------------------------------------------------------------
# Step 2: Table flattening
# ---------------------------------------------------------------------------

def step2_flatten_tables(text: str) -> str:
    return flatten_tables_in_text(text)


# ---------------------------------------------------------------------------
# Step 2b: Text cleaning (safe features from text_cleaner.py)
#   - 불릿 기호 정규화 (○□❍… → "- ")
#   - Bold markdown 제거 (**text** → text)
#   - 반복 머리말/꼬리말/페이지번호 제거
#   - 공백 정규화 (탭→스페이스, trailing WS, 연속 빈줄 축소)
#
#   ❌ 적용 안 함:
#   - Heading markdown 제거 → Step 4 헤더 삽입과 충돌
#   - 수평선 제거 → HWP 전용 (PDF 파이프라인에 불필요)
# ---------------------------------------------------------------------------

def step2b_clean_text(text: str) -> str:
    """파이프라인을 망가뜨리지 않는 text_cleaner 기능만 선별 적용."""
    result = text

    # 1. 불릿 기호 정규화
    result = _BULLET_RE.sub(r"\1- ", result)
    result = _BACKTICK_BULLET_RE.sub(r"\1- ", result)

    # 2. Bold markdown 제거
    result = _BOLD_RE.sub(r"\1", result)

    # 3. 반복 머리말/꼬리말 제거
    for pattern in _HEADER_FOOTER_PATTERNS:
        result = pattern.sub("", result)

    # 4. 공백 정규화
    result = result.replace("\t", "    ")
    result = _TRAILING_WS_RE.sub("", result)
    result = _MULTI_BLANK_RE.sub("\n\n", result)

    return result


# ---------------------------------------------------------------------------
# Step 3: Regex-based section hierarchy extraction
# ---------------------------------------------------------------------------

def _find_page2_position(text: str) -> int:
    """[[PAGE:2]] 위치 → 첫 페이지 경계. 없으면 0 (스킵 없음)."""
    for m in _PAGE_MARKER_OLD_RE.finditer(text):
        if int(m.group(1)) == 2:
            return m.start()
    return 0


def step3_extract_hierarchy(text: str) -> List[Tuple[str, int, int]]:
    """정규식 기반 섹션 계층 구조 추출. 첫 페이지 제목은 건너뜀.

    Returns:
        [(heading_text, level, char_position), ...]
    """
    page2_pos = _find_page2_position(text)

    all_matches: List[Tuple[str, str, int]] = []
    seen_positions: set = set()

    def _add(regex: re.Pattern, type_name: str) -> None:
        for m in regex.finditer(text):
            if m.start() < page2_pos:
                continue
            if m.start() in seen_positions:
                continue
            seen_positions.add(m.start())
            all_matches.append((m.group(1).strip(), type_name, m.start()))

    # Group A
    for m in _LEGAL_RE.finditer(text):
        if m.start() < page2_pos:
            continue
        if m.start() in seen_positions:
            continue
        heading = m.group(1).strip()
        type_match = _LEGAL_TYPE_RE.search(heading)
        if type_match:
            seen_positions.add(m.start())
            all_matches.append(
                (heading, f"제N{type_match.group(1)}", m.start()),
            )

    # Group B (d3 → d2 → d1 순서 — 상위 depth 먼저 등록해서 중복 방지)
    _add(_NUMBERED_D3_RE, "numbered_d3")
    _add(_NUMBERED_D2_RE, "numbered_d2")
    _add(_NUMBERED_D1_RE, "numbered_d1")
    _add(_ROMAN_RE, "roman")
    _add(_KOREAN_LETTER_RE, "korean_letter")
    _add(_BRACKET_RE, "bracket")

    all_matches.sort(key=lambda x: x[2])

    # ── Bracket validation: bracket 뒤에 다른 L1 타입이 나오면 bracket 제외 ──
    _l1_types: set = set()
    _detected_legal_for_filter: set = set()
    for _, _tn, _ in all_matches:
        if _tn.startswith('제N'):
            _detected_legal_for_filter.add(_tn[2:])
    for _k in LEGAL_ORDER:
        if _k in _detected_legal_for_filter:
            _l1_types.add(f'제N{_k}')
            break
    if not _l1_types:
        for _, _tn, _ in all_matches:
            if _tn != 'bracket' and not _tn.startswith('제N'):
                _l1_types.add(_tn)
                break
    _last_l1_pos = max((p for _, t, p in all_matches if t in _l1_types), default=-1)
    all_matches = [(h, t, p) for h, t, p in all_matches if t != 'bracket' or p > _last_l1_pos]

    # --- Level assignment ---
    type_level_map: Dict[str, int] = {}
    max_level = 0

    # Phase 1: Group A — 존재하는 법적 유형만, 표준 순서대로
    detected_legal: set = set()
    for _, type_name, _ in all_matches:
        if type_name.startswith("제N"):
            detected_legal.add(type_name[2:])

    for k in LEGAL_ORDER:
        if k in detected_legal:
            max_level += 1
            type_level_map[f"제N{k}"] = max_level

    # Auditor가 이미 #/## 삽입한 경우 L1/L2는 점유된 것으로 간주
    if max_level < 2:
        if re.search(r'^## ', text, re.MULTILINE):
            max_level = max(max_level, 2)
        elif re.search(r'^# ', text, re.MULTILINE):
            max_level = max(max_level, 1)

    # Phase 2: Group B — 첫 등장 순서대로 max_level + 1 (bracket은 항상 L1)
    result: List[Tuple[str, int, int]] = []
    for heading_text, type_name, position in all_matches:
        if type_name == "bracket":
            level = 1
        elif type_name in type_level_map:
            level = type_level_map[type_name]
        else:
            max_level += 1
            level = max_level
            type_level_map[type_name] = level
        result.append((heading_text, level, position))

    return result


# ---------------------------------------------------------------------------
# Step 4: Header insertion
# ---------------------------------------------------------------------------

def step4_insert_headers(
    text: str, hierarchy: List[Tuple[str, int, int]],
) -> str:
    """레벨 1 → '#', 레벨 2 → '##'. 레벨 3+ → 마크다운 헤더 없음."""
    if not hierarchy:
        return text

    # 뒤에서부터 삽입 → 앞쪽 position 보존
    for _heading_text, level, position in reversed(hierarchy):
        if level > 2:
            continue
        prefix = "# " if level == 1 else "## "
        text = text[:position] + prefix + text[position:]

    return text


# ---------------------------------------------------------------------------
# Step 5: Page marker conversion
# ---------------------------------------------------------------------------

def step5_convert_page_markers(text: str) -> str:
    """[[PAGE:N]] → paragraph-separated [[[Page: N]]]"""
    def _replace(m: re.Match) -> str:
        return f"\n\n[[[Page: {m.group(1)}]]]\n\n"
    return _PAGE_MARKER_OLD_RE.sub(_replace, text)




def _extract_page_range(text: str) -> Tuple[Optional[int], Optional[int]]:
    """[[[Page: N]]] 마커에서 페이지 범위 추출."""
    pages = [int(m.group(1)) for m in _PAGE_MARKER_NEW_RE.finditer(text)]
    if pages:
        return min(pages), max(pages)
    return None, None


def _remove_page_markers(text: str) -> str:
    """페이지 마커 제거 후 연속 빈줄 정리."""
    result = _PAGE_MARKER_NEW_RE.sub('', text)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()

# ---------------------------------------------------------------------------
# Step 6: Section map + RecursiveCharacterTextSplitter
#   MarkdownHeaderTextSplitter 를 제거하고, 섹션 맵 기반으로 메타데이터 할당.
#   헤더만 단독 chunk로 잘려나가는 문제를 방지한다.
# ---------------------------------------------------------------------------

_H1_RE = re.compile(r'^# (.+)$', re.MULTILINE)
_H2_RE = re.compile(r'^## (.+)$', re.MULTILINE)


def _build_section_map(text: str) -> List[Tuple[int, str, str]]:
    """텍스트의 # / ## 헤더를 스캔하여 섹션 맵을 생성.

    Returns:
        [(char_position, section_level1, section_level2), ...]
        위치순 정렬. 각 항목은 '이 위치부터 다음 항목 전까지' 적용되는 섹션을 나타냄.
    """
    entries: List[Tuple[int, str, str]] = []
    current_l1 = 'N/A'
    current_l2 = 'N/A'

    # 모든 헤더를 찾아서 위치순으로 정렬
    headers: List[Tuple[int, int, str]] = []  # (position, level, heading_text)
    for m in _H1_RE.finditer(text):
        headers.append((m.start(), 1, m.group(1).strip()))
    for m in _H2_RE.finditer(text):
        headers.append((m.start(), 2, m.group(1).strip()))
    headers.sort(key=lambda x: x[0])

    # 문서 시작부터 첫 헤더 전까지의 기본 섹션
    entries.append((0, current_l1, current_l2))

    for pos, level, heading in headers:
        if level == 1:
            current_l1 = heading
            current_l2 = 'N/A'  # L1 변경 시 L2 리셋
        else:  # level == 2
            current_l2 = heading
        entries.append((pos, current_l1, current_l2))

    return entries


def _find_section(section_map: List[Tuple[int, str, str]], position: int) -> Tuple[str, str]:
    """주어진 문자 위치가 속한 섹션의 (L1, L2) 반환.

    section_map 은 위치순 정렬되어 있으므로 역순 검색.
    """
    result_l1 = 'N/A'
    result_l2 = 'N/A'
    for map_pos, l1, l2 in reversed(section_map):
        if position >= map_pos:
            result_l1 = l1
            result_l2 = l2
            break
    return result_l1, result_l2


def step6_section_split(text: str) -> List[Dict]:
    """섹션 맵 구축 → 페이지 마커 제거 → RecursiveCharacterTextSplitter → 메타데이터 할당.

    MarkdownHeaderTextSplitter를 대체하여 헤더가 본문과 분리되지 않도록 한다.

    Returns:
        [{'page_content': str, 'metadata': {'section_level1', 'section_level2',
         'page_start', 'page_end'}}, ...]
    """
    # 1. 섹션 맵 구축 (페이지 마커 제거 전, 원본 위치 기준)
    section_map = _build_section_map(text)

    # 2. 페이지 범위 추출을 위한 전체 페이지 마커 수집
    page_markers_by_pos: List[Tuple[int, int]] = []  # (char_pos, page_num)
    for m in _PAGE_MARKER_NEW_RE.finditer(text):
        page_markers_by_pos.append((m.start(), int(m.group(1))))

    # 3. 페이지 마커 제거 후 텍스트 준비
    clean_text = _remove_page_markers(text)

    # 4. RecursiveCharacterTextSplitter로 분할
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    raw_chunks = splitter.split_text(clean_text)

    # 5. 각 chunk에 섹션/페이지 메타데이터 할당
    results: List[Dict] = []
    search_start = 0
    last_page_start = 1
    last_page_end = 1
    for chunk_text in raw_chunks:
        chunk_text = chunk_text.strip()
        if not chunk_text:
            continue

        # chunk의 원본 위치 찾기 (clean_text에서 순차 검색)
        chunk_pos = clean_text.find(chunk_text[:80], search_start)
        if chunk_pos == -1:
            chunk_pos = clean_text.find(chunk_text[:80])
        if chunk_pos >= 0:
            search_start = chunk_pos + 1

        # clean_text 위치 ≈ 원본 text 위치 (페이지 마커 제거 오프셋은 소량)
        orig_pos = chunk_pos if chunk_pos >= 0 else 0

        # 섹션 할당
        section_l1, section_l2 = _find_section(section_map, orig_pos)

        chunk_end = orig_pos + len(chunk_text)
        chunk_pages: List[int] = []
        nearest_before: Optional[int] = None
        for marker_pos, page_num in page_markers_by_pos:
            if orig_pos <= marker_pos <= chunk_end:
                chunk_pages.append(page_num)
            elif marker_pos < orig_pos:
                nearest_before = page_num
        if chunk_pages:
            page_start = min(chunk_pages)
            page_end = max(chunk_pages)
            last_page_start = page_start
            last_page_end = page_end
        elif nearest_before is not None:
            page_start = nearest_before
            page_end = nearest_before
            last_page_start = page_start
            last_page_end = page_end
        else:
            page_start = last_page_start
            page_end = last_page_end

        results.append({
            'page_content': chunk_text,
            'metadata': {
                'section_level1': section_l1,
                'section_level2': section_l2,
                'page_start': page_start,
                'page_end': page_end,
            },
        })

    return results


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def process_file(file_path: Path) -> List[Dict]:
    print(f"📄 Processing: {file_path.name}")
    document_title = unicodedata.normalize('NFC', file_path.stem)
    document_title = document_title.replace('step2_audited_', '')
    document_title = document_title.replace('step1_parsed_', '')
    text = file_path.read_text(encoding='utf-8')
    print(f"   Input: {len(text):,} chars")
    doc_meta, body = parse_frontmatter(text)
    doc_meta['document_title'] = document_title
    body = step2_flatten_tables(body)
    print(f"   Step 2 (table flatten): {len(body):,} chars")
    body = step2b_clean_text(body)
    print(f"   Step 2b (text clean): {len(body):,} chars")
    hierarchy = step3_extract_hierarchy(body)
    print(f"   Step 3 (hierarchy): {len(hierarchy)} headings")
    body = step4_insert_headers(body, hierarchy)

    body = step5_convert_page_markers(body)
    # Step 6: 섹션 맵 + RecursiveCharacterTextSplitter (헤더 단독 분리 방지)
    split_results = step6_section_split(body)
    print(f"   Step 6 (section split): {len(split_results)} chunks")
    source = doc_meta.get('source_file', 'Unknown')
    name = source.rsplit('.', 1)[0] if '.' in source else source
    institution = 'N/A'
    project_name = 'N/A'
    if '_' in name:
        institution, project_name = name.split('_', 1)

    chunks: List[Dict] = []
    for item in split_results:
        content = item['page_content']
        if not content:
            continue
        meta = item['metadata']
        chunks.append({
            'page_content': content,
            'metadata': {
                'document_title': doc_meta.get('document_title', 'Unknown'),
                'source': source,
                'section_level1': meta['section_level1'],
                'section_level2': meta['section_level2'],
                'page_start': meta['page_start'],
                'page_end': meta['page_end'],
                'institution': institution,
                'project_name': project_name,
                'chunk_size': len(content),
                'created_at': datetime.now().isoformat(),
            },
        })
    print(f"   Final: {len(chunks)} chunks")
    return chunks


def process_all_files(file_paths: List[Path], output_dir: Path) -> List[Dict]:
    all_chunks: List[Dict] = []
    global_chunk_id = 0

    for file_path in file_paths:
        file_chunks = process_file(file_path)

        for chunk in file_chunks:
            chunk['chunk_id'] = global_chunk_id
            chunk_file = output_dir / f"chunk_{global_chunk_id:05d}.json"
            with open(chunk_file, 'w', encoding='utf-8') as f:
                json.dump(chunk, f, ensure_ascii=False, indent=2)
            all_chunks.append(chunk)
            global_chunk_id += 1

    return all_chunks


def print_statistics(chunks: List[Dict]) -> None:
    if not chunks:
        print("⚠️  No chunks generated")
        return

    total = len(chunks)
    total_size = sum(c['metadata']['chunk_size'] for c in chunks)
    avg = total_size / total
    mn = min(c['metadata']['chunk_size'] for c in chunks)
    mx = max(c['metadata']['chunk_size'] for c in chunks)

    print("\n" + "=" * 60)
    print("📊 Chunking Statistics")
    print("=" * 60)
    print(f"Total chunks: {total}")
    print(f"Total content: {total_size:,} chars")
    print(f"Avg / Min / Max: {avg:.0f} / {mn} / {mx}")

    print(f"\n📌 First chunk sample:")
    print(f"Chunk ID: {chunks[0]['chunk_id']}")
    print(f"Content: {chunks[0]['page_content'][:150]}...")
    print(json.dumps(chunks[0]['metadata'], ensure_ascii=False, indent=2))

    print("\n✨ Chunker completed successfully!")


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("✂️  CHUNKER STAGE (v3.1 Pipeline)")
    print("=" * 60 + "\n")

    from src.utils.config import PROJECT_ROOT
    input_dir = PROJECT_ROOT / 'output'
    output_dir = PROJECT_ROOT / 'output' / 'chunks'
    output_dir.mkdir(parents=True, exist_ok=True)

    final_files = sorted(input_dir.glob('step2_audited_*.md'))
    if not final_files:
        print("⚠️  No step2_audited_*.md found, trying step1_parsed_*.md...")
        final_files = sorted(input_dir.glob('step1_parsed_*.md'))

    if not final_files:
        print("❌ No input files found")
        exit(1)

    print(f"Found {len(final_files)} files to process\n")

    all_chunks = process_all_files(final_files, output_dir)
    print_statistics(all_chunks)
    print(f"\n📁 Output: {output_dir.absolute()}")
