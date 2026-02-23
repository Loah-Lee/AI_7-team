"""
Auditor Step 2: Text cleanup for parsed markdown files.
- Fixes Korean single-char spacing (with safety threshold)
- Standardizes bullet characters (○●■※ → *)
- Merges conditional line breaks in table cells
- Collapses whitespace
- Preserves YAML frontmatter and [[PAGE:n]] markers
"""

import re
from pathlib import Path
from typing import List

_PAGE_MARKER_RE = re.compile(r'<<PAGE:\s*\d+>>')
_BULLET_RE = re.compile(r'^(\s*)[○●■※◆◇▶▷►]\s*', re.MULTILINE)
_SINGLE_CHAR_RE = re.compile(r'((?:[가-힣]\s){2,}[가-힣])')

# 단일글자 교정으로 텍스트 길이가 15% 이상 변하면 교정 취소
SPACING_SAFETY_RATIO = 0.15


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
