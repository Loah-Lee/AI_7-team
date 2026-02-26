"""Auditor Step 2: 7-Step Markdown Audit Pipeline.

Steps:
  1. (Pre) PDF → markdown (done by preprocessor)
  2. Normalize: bold merge, roman normalize, strip parser headers
  3. Find hierarchy value candidates
  4. Filter inappropriate candidates
  5. Determine L1/L2 by appearance order
  6. Insert page markers at page boundaries
  7. Insert headers based on hierarchy
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_PAGE_MARKER_RE = re.compile(r'<<PAGE:\s*\d+>>')
_PAGE_NUM_RE = re.compile(r'<<PAGE:\s*(\d+)>>')

_BULLET_RE = re.compile(r'^(\s*)[○●■※◆◇▶▷►]\s*', re.MULTILINE)
_SINGLE_CHAR_RE = re.compile(r'((?:[가-힣]\s){2,}[가-힣])')
_BOLD_STRIP_RE = re.compile(r'\*\*(.+?)\*\*')
_CONSECUTIVE_BOLD_RE = re.compile(r'\*\*(.+?)\*\*\s*\*\*(.+?)\*\*')
_MD_HEADER_RE = re.compile(r'^#+\s')

SPACING_SAFETY_RATIO = 0.15

# Heading patterns
_H_LEGAL_RE = re.compile(
    r"^(제\s*\d+\s*[장절조편항][\s.:]\s*.+)$", re.MULTILINE,
)
_H_LEGAL_TYPE_RE = re.compile(r"제\s*\d+\s*([장절조편항])")
_H_NUMBERED_D3_RE = re.compile(
    r"^(\d+\.\d+\.\d+(?:\.\d+)*\.?\s+\S.+)$", re.MULTILINE,
)
_H_NUMBERED_D2_RE = re.compile(r"^(\d+\.\d+\.?\s+\S.+)$", re.MULTILINE)
_H_NUMBERED_D1_RE = re.compile(
    r"^((?:1[0-9]|[1-9])\.\s+\S.+)$", re.MULTILINE,
)
_H_ROMAN_RE = re.compile(
    r"^([IVXivxⅠ-Ⅻⅰ-ⅻ]+\.\s+\S.+)$", re.MULTILINE,
)
_H_KOREAN_LET_RE = re.compile(r"^([가-하]\.\s+\S.+)$", re.MULTILINE)
_H_BRACKET_RE = re.compile(r"^(\[.+\]\s*.*)$", re.MULTILINE)

LEGAL_ORDER = ["편", "장", "절", "조", "항"]

_HEADING_RE_NAMED = [
    ("legal",         _H_LEGAL_RE),
    ("numbered_d3",   _H_NUMBERED_D3_RE),
    ("numbered_d2",   _H_NUMBERED_D2_RE),
    ("numbered_d1",   _H_NUMBERED_D1_RE),
    ("roman",         _H_ROMAN_RE),
    ("korean_letter", _H_KOREAN_LET_RE),
    ("bracket",       _H_BRACKET_RE),
]

# 유효한 한글 말머리: 자음 + ㅏ, 받침 없음
_VALID_KOREAN_MARKERS = set('가나다라마바사아자차카타파하')

# 로마자 정규화: 로마 숫자 + (선택적 점) + 내용
_ROMAN_NORM_RE = re.compile(
    r'^([IVXivxⅠ-Ⅻⅰ-ⅻ]+)\s*\.?\s+(.+)$',
)


# ---------------------------------------------------------------------------
# Text cleanup helpers
# ---------------------------------------------------------------------------

def fix_single_char_spacing(text: str) -> str:
    """반복 단일 한글 글자 사이 공백 제거 (안전 비율 초과 시 원본 반환)."""
    original_len = len(text)
    result = _SINGLE_CHAR_RE.sub(lambda m: m.group(0).replace(' ', ''), text)
    if original_len > 0 and abs(len(result) - original_len) / original_len > SPACING_SAFETY_RATIO:
        return text
    return result


def standardize_bullets(text: str) -> str:
    """다양한 불릿 기호 → '* ' 표준화."""
    return _BULLET_RE.sub(r'\1* ', text)


def merge_table_cell_linebreaks(text: str) -> str:
    """테이블 셀 내부 줄바꿈 병합."""
    lines = text.split('\n')
    merged: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith('|') and line.strip().endswith('|'):
            merged.append(line)
            i += 1
            continue
        if (merged
                and merged[-1].strip().startswith('|')
                and merged[-1].strip().endswith('|')):
            stripped = line.strip()
            if (stripped
                    and not stripped.startswith('|')
                    and not stripped.startswith('#')
                    and not _PAGE_MARKER_RE.match(stripped)):
                merged[-1] = merged[-1].rstrip() + ' ' + stripped
                i += 1
                continue
        merged.append(line)
        i += 1
    return '\n'.join(merged)


def cleanup_whitespace(text: str) -> str:
    """연속 공백/빈줄 정규화."""
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


# ---------------------------------------------------------------------------
# Pipeline step functions
# ---------------------------------------------------------------------------

def _split_by_page_markers(body: str) -> List[Tuple[int, str]]:
    """페이지 마커 기준으로 본문 분할.

    Returns:
        [(page_num, content), ...]
    """
    parts = _PAGE_NUM_RE.split(body)
    if len(parts) < 2:
        return [(1, body.strip())]

    pages: List[Tuple[int, str]] = []
    for i in range(1, len(parts), 2):
        page_num = int(parts[i])
        content = parts[i + 1].strip() if i + 1 < len(parts) else ''
        pages.append((page_num, content))
    return pages


def _step2_normalize(text: str) -> str:
    """Step 2: Markdown 정규화.

    실행 순서: 텍스트 정리 → 2-3 헤더 제거 → 2-1 bold 병합 → 2-2 로마자 정규화
    (헤더 제거를 먼저 해야 로마자 정규화가 올바르게 동작)
    """
    # 기존 텍스트 정리
    text = fix_single_char_spacing(text)
    text = standardize_bullets(text)
    text = merge_table_cell_linebreaks(text)
    text = cleanup_whitespace(text)

    lines = text.split('\n')

    # 2-3) Parser 삽입 헤더 제거: '# text' → 'text', '### text' → 'text'
    for i, line in enumerate(lines):
        m = _MD_HEADER_RE.match(line)
        if m:
            lines[i] = line[m.end():]

    # 2-1) 연속 bold 병합: **A** **B** → **A B**
    for i, line in enumerate(lines):
        prev = None
        while prev != line:
            prev = line
            line = _CONSECUTIVE_BOLD_RE.sub(r'**\1 \2**', line)
        lines[i] = line

    # 2-2) 로마자 숫자 정규화 (단락 시작인 경우만)
    for i, line in enumerate(lines):
        is_para_start = (i == 0) or (lines[i - 1].strip() == '')
        if not is_para_start:
            continue
        s = line.strip()
        if not s:
            continue

        # bold 제거 후 로마자 검사
        clean = _BOLD_STRIP_RE.sub(r'\1', s)
        m = _ROMAN_NORM_RE.match(clean)
        if m:
            roman_part = m.group(1)
            rest_part = m.group(2).strip()
            is_full_bold = s.startswith('**') and s.endswith('**')
            if is_full_bold:
                lines[i] = f'**{roman_part}. {rest_part}**'
            else:
                lines[i] = f'{roman_part}. {rest_part}'

    return '\n'.join(lines)


def _step3_find_candidates(
    text: str,
) -> List[Tuple[int, str, str]]:
    """Step 3: 계층 값 후보 수집.

    Returns:
        [(line_idx, type_name, heading_text), ...]
    """
    candidates: List[Tuple[int, str, str]] = []
    lines = text.split('\n')

    for idx, line in enumerate(lines):
        s = line.strip()
        if not s or _PAGE_MARKER_RE.match(s) or s.startswith('|'):
            continue

        matched_type: Optional[str] = None
        for type_name, regex in _HEADING_RE_NAMED:
            if type_name == 'bracket':
                continue  # bracket 무시
            if regex.match(s):
                if type_name == 'legal':
                    m = _H_LEGAL_TYPE_RE.search(s)
                    matched_type = f'제N{m.group(1)}' if m else None
                else:
                    matched_type = type_name
                break

        if matched_type:
            candidates.append((idx, matched_type, s))

    return candidates


def _step4_filter_candidates(
    candidates: List[Tuple[int, str, str]],
) -> List[Tuple[int, str, str]]:
    """Step 4: 부적절한 후보 제거.

    - 모음이 ㅏ가 아니거나 받침이 있는 한글 (그., 후., 강., 삼.)
    """
    filtered: List[Tuple[int, str, str]] = []
    for idx, type_name, heading_text in candidates:
        # 한글 말머리 필터: 가나다라마바사아자차카타파하 만 허용
        if type_name == 'korean_letter':
            first_char = heading_text[0]
            if first_char not in _VALID_KOREAN_MARKERS:
                continue

        filtered.append((idx, type_name, heading_text))

    return filtered


def _step5_determine_levels(
    candidates: List[Tuple[int, str, str]],
) -> Dict[str, int]:
    """Step 5: 등장 순서 기반 L1/L2 결정.

    첫 타입 → L1, 다음 다른 타입 → L2.
    bracket은 이미 제외됨.
    """
    if not candidates:
        return {}

    l1_type: Optional[str] = None
    l2_type: Optional[str] = None

    for _, type_name, _ in candidates:
        if l1_type is None:
            l1_type = type_name
        elif type_name != l1_type and l2_type is None:
            l2_type = type_name
            break

    result: Dict[str, int] = {}
    if l1_type:
        result[l1_type] = 1
    if l2_type:
        result[l2_type] = 2

    if result:
        print(f'📋 Level mapping (order-based): {result}')

    return result


def _step6_insert_page_markers(
    normalized_pages: List[Tuple[int, str]],
) -> str:
    """Step 6: 정규화된 페이지들에 page marker 재삽입."""
    parts: List[str] = []
    for page_num, content in normalized_pages:
        parts.append(f'<<PAGE: {page_num}>>')
        parts.append('')
        if content:
            parts.append(content)
        parts.append('')
    return '\n'.join(parts)


def _step7_insert_headers(
    text: str,
    type_level_map: Dict[str, int],
) -> str:
    """Step 7: 계층 매핑 기반 헤더 삽입.

    순차적으로 텍스트를 스캔, type_level_map에 매칭되는 라인에 #/## 삽입.
    """
    if not type_level_map:
        return text

    lines = text.split('\n')

    for idx, line in enumerate(lines):
        s = line.strip()
        if not s or _PAGE_MARKER_RE.match(s) or s.startswith('|'):
            continue

        matched_type: Optional[str] = None
        for type_name, regex in _HEADING_RE_NAMED:
            if type_name == 'bracket':
                continue
            if regex.match(s):
                if type_name == 'legal':
                    m = _H_LEGAL_TYPE_RE.search(s)
                    matched_type = f'제N{m.group(1)}' if m else None
                else:
                    matched_type = type_name
                break

        if matched_type and matched_type in type_level_map:
            level = type_level_map[matched_type]
            prefix = '# ' if level == 1 else '## '
            lines[idx] = prefix + line

    return '\n'.join(lines)


# TOC separator pattern: 3+ consecutive dashes, dots, or middle dots
_TOC_SEP_RE = re.compile(r'[-\u00b7\u2015\u2500\u2501\u2502\u2503\u2550\u2551\u2026\u22ef\u00b7\u30fb·.─━]{5,}')
# Trailing page number after separators
_TOC_TRAILING_NUM_RE = re.compile(r'\s+\d+\s*$')


def _normalize_heading_title(raw: str) -> str:
    """Heading 제목 정규화: TOC 구분자, 후행 페이지 번호, 공백 정리."""
    t = raw.strip()
    t = _TOC_SEP_RE.sub('', t)
    t = _TOC_TRAILING_NUM_RE.sub('', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _strip_toc_duplicate_headers(text: str) -> str:
    """TOC 페이지의 중복 heading 제거.

    1. 페이지 마커 기준으로 페이지 분할
    2. TOC 페이지 탐지 (구분자 비율 > 50%)
    3. TOC 페이지의 heading 중 본문에도 동일 제목이 있는 경우 # 제거
    4. 본문에만 있는 heading은 유지 (목차 하단 본문 시작 가능)
    """
    pages_raw = _PAGE_NUM_RE.split(text)
    if len(pages_raw) < 2:
        return text

    # 페이지별 라인 수집
    page_data: List[Tuple[int, List[str]]] = []
    for i in range(1, len(pages_raw), 2):
        pnum = int(pages_raw[i])
        content = pages_raw[i + 1] if i + 1 < len(pages_raw) else ''
        page_data.append((pnum, content.split('\n')))

    # TOC 페이지 탐지: 구분자 라인 비율 > 50%
    toc_pages: Set[int] = set()
    for pnum, lines in page_data:
        non_empty = [l for l in lines if l.strip()]
        if not non_empty:
            continue
        sep_count = sum(1 for l in non_empty if _TOC_SEP_RE.search(l))
        if sep_count / len(non_empty) > 0.5:
            toc_pages.add(pnum)

    if not toc_pages:
        return text

    # 전체 heading 수집: normalized_title -> [(page, line_idx, is_toc_page)]
    heading_map: Dict[str, List[Tuple[int, int, bool]]] = {}
    for pnum, lines in page_data:
        is_toc = pnum in toc_pages
        for li, line in enumerate(lines):
            m = _MD_HEADER_RE.match(line)
            if m:
                title_part = line[m.end():].strip()
                norm = _normalize_heading_title(title_part)
                if norm:
                    heading_map.setdefault(norm, []).append((pnum, li, is_toc))

    # 중복 heading 찾기: TOC에도 있고 본문에도 있는 것
    toc_dup_keys: Set[str] = set()
    for norm, locs in heading_map.items():
        has_toc = any(is_toc for _, _, is_toc in locs)
        has_body = any(not is_toc for _, _, is_toc in locs)
        if has_toc and has_body:
            toc_dup_keys.add(norm)

    if not toc_dup_keys:
        return text

    # TOC 페이지에서 중복 heading의 # 제거
    removed = 0
    for pnum, lines in page_data:
        if pnum not in toc_pages:
            continue
        for li, line in enumerate(lines):
            m = _MD_HEADER_RE.match(line)
            if m:
                title_part = line[m.end():].strip()
                norm = _normalize_heading_title(title_part)
                if norm in toc_dup_keys:
                    lines[li] = line[m.end():]  # # 제거, 내용만 유지
                    removed += 1

    if removed:
        print(f"   TOC cleanup: {removed} duplicate headings stripped from pages {sorted(toc_pages)}")

    # 재조립
    parts: List[str] = []
    if pages_raw[0].strip():
        parts.append(pages_raw[0])
    for pnum, lines in page_data:
        parts.append(f'<<PAGE: {pnum}>>')
        parts.append('\n'.join(lines))
    return '\n'.join(parts)


def validate_tables(text: str) -> None:
    """테이블 라인 수 출력 (진단용)."""
    table_lines = [line for line in text.split('\n') if line.startswith('|')]
    print(f"📊 Table validation: {len(table_lines)} lines starting with |")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def audit_file(input_path: str, output_path: str) -> None:
    """7-Step Auditor Pipeline."""
    print(f"🔍 Auditing: {input_path}")

    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Parse frontmatter
    parts = content.split('---', 2)
    if len(parts) >= 3 and parts[0].strip() == '':
        frontmatter = parts[1]
        body = parts[2]
        has_frontmatter = True
    else:
        frontmatter = ''
        body = content
        has_frontmatter = False

    # --- Pre: 페이지별 분할 ---
    pages = _split_by_page_markers(body)
    print(f"   Pages: {len(pages)}")

    # --- Step 2: 페이지별 정규화 ---
    normalized_pages = [(pnum, _step2_normalize(page_content))
                        for pnum, page_content in pages]

    # --- Bold 전체 제거 (step 2 완료 후, step 3 전) ---
    # step 2-2 로마자 정규화에서 is_full_bold 판별이 필요하므로
    # step 2 내부가 아닌 완료 후에 제거한다.
    normalized_pages = [(pnum, _BOLD_STRIP_RE.sub(r'\1', content))
                        for pnum, content in normalized_pages]

    # Steps 3-5: 전체 텍스트에서 수행 (마커 없이)
    combined = '\n\n'.join(c for _, c in normalized_pages)

    # --- Step 3: 계층 값 후보 수집 ---
    candidates = _step3_find_candidates(combined)
    print(f"   Step 3: {len(candidates)} candidates")

    # --- Step 4: 부적절한 후보 제거 ---
    filtered = _step4_filter_candidates(candidates)
    removed = len(candidates) - len(filtered)
    print(f"   Step 4: {len(filtered)} after filter (-{removed})")

    # --- Step 5: L1/L2 결정 ---
    type_level_map = _step5_determine_levels(filtered)

    # --- Step 6: 페이지 마커 재삽입 ---
    body_with_markers = _step6_insert_page_markers(normalized_pages)

    # --- Step 7: 헤더 삽입 ---
    body_final = _step7_insert_headers(body_with_markers, type_level_map)

    # --- TOC 중복 heading 제거 (step 7 후, chunker 전) ---
    body_final = _strip_toc_duplicate_headers(body_final)

    validate_tables(body_final)

    # Output
    if has_frontmatter:
        output_content = f"---{frontmatter}---{body_final}"
    else:
        output_content = body_final

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output_content)

    print(f"✅ Audited: {output_path}")


if __name__ == '__main__':
    from src.utils.config import PROJECT_ROOT
    input_dir = PROJECT_ROOT / 'output'
    parsed_files = sorted(input_dir.glob('step1_parsed_*.md'))

    if not parsed_files:
        print("⚠️ No step1_parsed_*.md files found in output/")
    else:
        for parsed_file in parsed_files:
            stem = parsed_file.stem.replace('step1_parsed_', '')
            output_path = input_dir / f'step2_audited_{stem}.md'
            audit_file(str(parsed_file), str(output_path))

        print(f"\n✨ Auditor complete: {len(parsed_files)} file(s) processed")
