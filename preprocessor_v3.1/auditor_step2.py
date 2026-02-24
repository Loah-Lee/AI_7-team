"""
Auditor Step 2: Text cleanup + TOC detection for parsed markdown files.
"""
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
_PAGE_MARKER_RE = re.compile(r'<<PAGE:\s*\d+>>')
_PAGE_NUM_RE = re.compile(r'<<PAGE:\s*(\d+)>>')
_BULLET_RE = re.compile(r'^(\s*)[○●■※◆◇▶▷►]\s*', re.MULTILINE)
_SINGLE_CHAR_RE = re.compile(r'((?:[가-힣]\s){2,}[가-힣])')
_BOLD_STRIP_RE = re.compile(r'\*\*(.+?)\*\*')

SPACING_SAFETY_RATIO = 0.15

_H_LEGAL_RE = re.compile(r"^(제\s*\d+\s*[장절조편항][\s.:]\s*.+)$", re.MULTILINE)
_H_NUMBERED_D3_RE = re.compile(r"^(\d+\.\d+\.\d+(?:\.\d+)*\.?\s+\S.+)$", re.MULTILINE)
_H_NUMBERED_D2_RE = re.compile(r"^(\d+\.\d+\.?\s+\S.+)$", re.MULTILINE)
_H_NUMBERED_D1_RE = re.compile(r"^(\d{1,2}\.\s+\S.+)$", re.MULTILINE)
_H_ROMAN_RE = re.compile(r"^([IVXivxⅠ-Ⅻⅰ-ⅻ]+\.\s+\S.+)$", re.MULTILINE)
_H_KOREAN_LET_RE = re.compile(r"^([가-하]\.\s+\S.+)$", re.MULTILINE)
_H_BRACKET_RE = re.compile(r"^(\[.+\]\s*.*)$", re.MULTILINE)
_ALL_HEADING_RE = [
    _H_LEGAL_RE, _H_NUMBERED_D3_RE, _H_NUMBERED_D2_RE,
    _H_NUMBERED_D1_RE, _H_ROMAN_RE, _H_KOREAN_LET_RE, _H_BRACKET_RE,
]

_H_LEGAL_TYPE_RE = re.compile(r"제\s*\d+\s*([장절조편항])")
LEGAL_ORDER = ["편", "장", "절", "조", "항"]

_HEADING_RE_NAMED = [
    ("legal",        _H_LEGAL_RE),
    ("numbered_d3",  _H_NUMBERED_D3_RE),
    ("numbered_d2",  _H_NUMBERED_D2_RE),
    ("numbered_d1",  _H_NUMBERED_D1_RE),
    ("roman",        _H_ROMAN_RE),
    ("korean_letter", _H_KOREAN_LET_RE),
    ("bracket",      _H_BRACKET_RE),
]


def fix_single_char_spacing(text: str) -> str:
    original_len = len(text)
    result = _SINGLE_CHAR_RE.sub(lambda m: m.group(0).replace(' ', ''), text)
    if original_len > 0 and abs(len(result) - original_len) / original_len > SPACING_SAFETY_RATIO:
        return text
    return result


def standardize_bullets(text: str) -> str:
    return _BULLET_RE.sub(r'\1* ', text)


def merge_table_cell_linebreaks(text: str) -> str:
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
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


# ---------------------------------------------------------------------------
# TOC detection (2-pass: heading extraction → pattern-only consecutive block)
# ---------------------------------------------------------------------------


def _get_page_ranges(text: str) -> List[Tuple[int, int, int]]:
    markers = list(_PAGE_NUM_RE.finditer(text))
    if not markers:
        return []
    pages = []
    for i, m in enumerate(markers):
        pnum = int(m.group(1))
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        pages.append((pnum, start, end))
    return pages


def _is_heading_line(line: str) -> bool:
    for regex in _ALL_HEADING_RE:
        if regex.match(line):
            return True
    return False


def _classify_page(page_text: str) -> Tuple[int, int]:
    clean = _BOLD_STRIP_RE.sub(r'\1', page_text)
    headings, contents = 0, 0
    for line in clean.split('\n'):
        s = line.strip()
        if not s or _PAGE_MARKER_RE.match(s) or s.startswith('#'):
            continue
        if _is_heading_line(s):
            headings += 1
        else:
            contents += 1
    return headings, contents


def detect_toc_pages(text: str) -> Set[int]:
    pages = _get_page_ranges(text)
    if not pages:
        return set()

    toc_pages: Set[int] = set()
    toc_started = False

    for pnum, start, end in pages:
        h, c = _classify_page(text[start:end])
        is_pattern_only = (h >= 3 and c == 0)

        if is_pattern_only:
            if not toc_started:
                toc_started = True
            toc_pages.add(pnum)
        elif toc_started:
            break

    return toc_pages


def neutralize_toc(text: str, toc_pages: Set[int]) -> str:
    if not toc_pages:
        return text
    pages = _get_page_ranges(text)
    for pnum, start, end in reversed(pages):
        if pnum not in toc_pages:
            continue
        page_text = text[start:end]
        lines = page_text.split('\n')
        indented = []
        for line in lines:
            s = line.strip()
            if not s or _PAGE_MARKER_RE.match(s) or s.startswith('|'):
                indented.append(line)
            else:
                indented.append('  ' + line)
        text = text[:start] + '\n'.join(indented) + text[end:]
    return text


# ---------------------------------------------------------------------------
# TOC-based heading type → level mapping (Selection Stage)
# ---------------------------------------------------------------------------

# 목차 줄 끝의 점선·페이지번호 제거용
_TOC_TRAIL_RE = re.compile(r'\s*[·\u00b7…⋯·\.]+[\s\d]*$')


def _extract_toc_heading_types(
    text: str, toc_pages: Set[int],
) -> Dict[str, int]:
    """목차(TOC) 페이지를 파싱하여 heading type → level 매핑을 생성한다.

    Bold 항목 → L1, non-bold 항목 → L2.
    neutralize_toc() 호출 전에 실행해야 한다 (원본 TOC 텍스트 필요).

    Returns:
        Dict[str, int]: e.g. {'roman': 1, 'bracket': 1, 'numbered_d1': 2}
    """
    if not toc_pages:
        return {}

    pages = _get_page_ranges(text)
    l1_types: Set[str] = set()
    l2_types: Set[str] = set()

    for pnum, start, end in pages:
        if pnum not in toc_pages:
            continue
        page_text = text[start:end]
        for line in page_text.split('\n'):
            s = line.strip()
            if not s or _PAGE_MARKER_RE.match(s) or s.startswith('#'):
                continue

            # bold 여부 판별
            is_bold = bool(re.match(r'^\*\*.+\*\*', s))

            # bold 제거 후 후행 점선·페이지번호 제거
            clean = _BOLD_STRIP_RE.sub(r'\1', s)
            clean = _TOC_TRAIL_RE.sub('', clean).strip()
            if not clean:
                continue

            # heading 패턴 매칭
            matched_type = None
            for type_name, regex in _HEADING_RE_NAMED:
                if regex.match(clean):
                    if type_name == 'legal':
                        m = _H_LEGAL_TYPE_RE.search(clean)
                        matched_type = f'제N{m.group(1)}' if m else None
                    else:
                        matched_type = type_name
                    break

            if not matched_type:
                continue

            if is_bold:
                l1_types.add(matched_type)
            else:
                l2_types.add(matched_type)

    # 매핑 생성: L1 우선, L2에만 있는 타입 추가
    result: Dict[str, int] = {}
    for t in l1_types:
        result[t] = 1
    for t in l2_types:
        if t not in result:
            result[t] = 2

    if result:
        print(f'📋 TOC type→level mapping: {result}')

    return result


# ---------------------------------------------------------------------------
# Body header insertion (Loop 2) — TOC mapping 기반
# ---------------------------------------------------------------------------


def insert_body_headers(
    text: str, toc_pages: Set[int], toc_type_level: Dict[str, int],
) -> str:
    """본문에서 TOC 매핑에 해당하는 heading만 #/## 삽입.

    toc_type_level이 비어 있으면 아무것도 삽입하지 않는다.
    """
    if not toc_type_level:
        return text

    pages = _get_page_ranges(text)
    if not pages:
        return text

    page2_start = 0
    for pnum, start, end in pages:
        if pnum >= 2:
            page2_start = start
            break

    def _pos_to_page(pos: int) -> int:
        for pn, s, e in pages:
            if s <= pos < e:
                return pn
        return -1

    lines = text.split('\n')
    assignments: List[Tuple[int, int]] = []

    char_pos = 0
    for idx, line in enumerate(lines):
        line_start = char_pos
        char_pos += len(line) + 1

        if line_start < page2_start:
            continue
        if _pos_to_page(line_start) in toc_pages:
            continue

        s = line.strip()
        if not s or _PAGE_MARKER_RE.match(s) or s.startswith('#') or s.startswith('|'):
            continue

        clean = _BOLD_STRIP_RE.sub(r'\1', s)

        # heading 패턴 매칭
        matched_type = None
        for type_name, regex in _HEADING_RE_NAMED:
            if regex.match(clean):
                if type_name == 'legal':
                    m = _H_LEGAL_TYPE_RE.search(clean)
                    matched_type = f'제N{m.group(1)}' if m else None
                else:
                    matched_type = type_name
                break

        # TOC 매핑에 있는 타입만 헤더 삽입
        if matched_type and matched_type in toc_type_level:
            level = toc_type_level[matched_type]
            if level <= 2:
                assignments.append((idx, level))

    if not assignments:
        return text

    for idx, level in reversed(assignments):
        prefix = '# ' if level == 1 else '## '
        lines[idx] = prefix + lines[idx]

    return '\n'.join(lines)


def _process_body(body: str) -> str:
    chunks: List[str] = []
    parts = _PAGE_MARKER_RE.split(body)
    markers = _PAGE_MARKER_RE.findall(body)

    for i, part in enumerate(parts):
        part = fix_single_char_spacing(part)
        part = standardize_bullets(part)
        part = merge_table_cell_linebreaks(part)
        part = cleanup_whitespace(part)
        chunks.append(part)
        if i < len(markers):
            chunks.append(markers[i])

    return ''.join(chunks)


def validate_tables(text: str) -> None:
    table_lines = [line for line in text.split('\n') if line.startswith('|')]
    print(f"📊 Table validation: {len(table_lines)} lines starting with |")


def audit_file(input_path: str, output_path: str) -> None:
    print(f"🔍 Auditing: {input_path}")

    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()

    parts = content.split('---', 2)
    if len(parts) >= 3 and parts[0].strip() == '':
        frontmatter = parts[1]
        body = parts[2]
        has_frontmatter = True
    else:
        frontmatter = ''
        body = content
        has_frontmatter = False

    body = _process_body(body)
    toc_pages = detect_toc_pages(body)
    toc_type_level: Dict[str, int] = {}
    if toc_pages:
        print(f"📑 TOC detected: pages {sorted(toc_pages)}")
        toc_type_level = _extract_toc_heading_types(body, toc_pages)
        body = neutralize_toc(body, toc_pages)
    body = insert_body_headers(body, toc_pages if toc_pages else set(), toc_type_level)
    validate_tables(body)

    if has_frontmatter:
        output_content = f"---{frontmatter}---{body}"
    else:
        output_content = body

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output_content)

    print(f"✅ Audited: {output_path}")


if __name__ == '__main__':
    input_dir = Path('output')
    parsed_files = sorted(input_dir.glob('step1_parsed_*.md'))

    if not parsed_files:
        print("⚠️ No step1_parsed_*.md files found in output/")
    else:
        for parsed_file in parsed_files:
            stem = parsed_file.stem.replace('step1_parsed_', '')
            output_path = input_dir / f'step2_audited_{stem}.md'
            audit_file(str(parsed_file), str(output_path))

        print(f"\n✨ Auditor complete: {len(parsed_files)} file(s) processed")
