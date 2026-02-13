"""
Auditor Step 2: Text cleanup for parsed markdown files.
- Fixes Korean single-char spacing patterns
- Collapses whitespace
- Validates tables
- Preserves YAML frontmatter and page markers
"""

import re
from pathlib import Path
from typing import Tuple


def fix_single_char_spacing(text: str) -> str:
    """
    Fix Korean single-character spacing patterns.
    Matches 2+ consecutive single Korean chars with spaces, collapses them.
    
    Examples:
    - "제 안 요 청 서" → "제안요청서"
    - "사 업 명" → "사업명"
    - "벤처기업 육성에 관한" → unchanged
    """
    pattern = r'((?:[가-힣]\s){2,}[가-힣])'
    
    def collapse(match):
        return match.group(0).replace(' ', '')
    
    return re.sub(pattern, collapse, text)


def cleanup_whitespace(text: str) -> str:
    """
    Collapse multiple spaces and newlines.
    - Multiple spaces → single space
    - 3+ newlines → 2 newlines
    """
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def validate_tables(text: str) -> None:
    """
    Log table statistics (lines starting with |).
    """
    table_lines = [line for line in text.split('\n') if line.startswith('|')]
    print(f"📊 Table validation: {len(table_lines)} lines starting with |")


def audit_file(input_path: str, output_path: str) -> None:
    """
    Read parsed markdown, apply cleanup, write audited markdown.
    
    Preserves:
    - YAML frontmatter (---...---)
    - Page markers (<!-- page: N -->)
    - Headers (# and ##)
    - Table markdown
    """
    print(f"🔍 Auditing: {input_path}")
    
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract YAML frontmatter
    parts = content.split('---', 2)
    if len(parts) >= 3 and parts[0].strip() == '':
        # Has frontmatter
        frontmatter = parts[1]
        body = parts[2]
        has_frontmatter = True
    else:
        # No frontmatter
        frontmatter = ''
        body = content
        has_frontmatter = False
    
    # Apply cleanup to body only
    body = fix_single_char_spacing(body)
    body = cleanup_whitespace(body)
    
    # Validate tables
    validate_tables(body)
    
    # Reconstruct with frontmatter
    if has_frontmatter:
        output_content = f"---{frontmatter}---{body}"
    else:
        output_content = body
    
    # Write output
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
