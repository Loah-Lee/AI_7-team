"""마크다운 테이블 → 자연어 텍스트 변환 모듈.

PDF 파서가 생성하는 마크다운 테이블(|Col1|Col2|...)을 자연어 형태로
평탄화하여 임베딩 유사도를 높인다.

Before: |사업명|차세대 포털|\n|---|---|\n|사업기간|24개월|
After:  사업명: 차세대 포털\n사업기간: 24개월
"""

from __future__ import annotations

import re

# 마크다운 테이블 행: | 로 시작하고 | 로 끝남
_TABLE_ROW_RE = re.compile(r"^\|.+\|$")
# 구분선: |---|---| 또는 |:---|:---| 등
_TABLE_SEP_RE = re.compile(r"^\|[-:\s|]+\|$")
# 플레이스홀더 헤더: Col1, Col2, Column1, ... 등
_PLACEHOLDER_HEADER_RE = re.compile(r"^(Col(umn)?\s*\d+)$", re.IGNORECASE)
# 한국어 일반 KV 헤더: "항목/내용", "구분/설명" 등 → 의미 없는 열 제목
_GENERIC_KV_HEADERS = {"항목", "내용", "구분", "설명", "비고", "분류", "세부내용"}
# <br> 태그
_BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _parse_cells(row: str) -> list[str]:
    """테이블 행에서 셀 값을 파싱한다."""
    # 양 끝 | 제거 후 | 로 분할
    inner = row.strip().strip("|")
    cells = [_BR_TAG_RE.sub(" ", c).strip() for c in inner.split("|")]
    return cells


def _is_separator_row(row: str) -> bool:
    """구분선 행인지 판별한다."""
    return bool(_TABLE_SEP_RE.match(row.strip()))


def _is_placeholder_header(headers: list[str]) -> bool:
    """헤더가 Col1/Col2 같은 플레이스홀더인지 판별한다."""
    return all(_PLACEHOLDER_HEADER_RE.match(h) for h in headers if h)


def _is_key_value_table(headers: list[str]) -> bool:
    """2열 key-value 테이블인지 판별한다."""
    return len(headers) == 2


def flatten_table(table_text: str) -> str:
    """마크다운 테이블을 자연어 텍스트로 변환한다.

    - 2열 key-value 테이블: "key: value" 형식
    - 다열 테이블: "header1: val1, header2: val2" (행별)
    - 플레이스홀더 헤더(Col1/Col2): 헤더 없이 값만 출력
    - 테이블 앞 텍스트(섹션 제목 등)는 보존

    Args:
        table_text: 마크다운 테이블 텍스트 (앞에 섹션 제목 포함 가능).

    Returns:
        자연어로 변환된 텍스트.
    """
    lines = table_text.split("\n")

    # 테이블 앞의 비테이블 텍스트(섹션 제목 등)를 분리
    prefix_lines: list[str] = []
    table_lines: list[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if _TABLE_ROW_RE.match(stripped):
            in_table = True
            table_lines.append(stripped)
        elif in_table:
            # 테이블 중간에 빈 줄이 나오면 테이블 끝으로 간주
            if stripped:
                table_lines.append(stripped)
            else:
                table_lines.append("")
        else:
            prefix_lines.append(line)

    if not table_lines:
        return table_text

    # 헤더/구분선/데이터 행 분리
    headers: list[str] = []
    data_rows: list[list[str]] = []

    for i, line in enumerate(table_lines):
        if not line.strip():
            continue
        if _is_separator_row(line):
            continue
        cells = _parse_cells(line)
        if i == 0 and not headers:
            headers = cells
        else:
            data_rows.append(cells)

    # 헤더만 있고 데이터 행이 없으면 원본 반환
    if not data_rows:
        return table_text

    placeholder = _is_placeholder_header(headers)
    kv_table = _is_key_value_table(headers) and not placeholder

    # KV 테이블에서는 헤더 행도 데이터 — 단, 일반적 열 제목은 제외
    if kv_table:
        header_vals = {h.strip() for h in headers if h.strip()}
        if not header_vals.issubset(_GENERIC_KV_HEADERS):
            data_rows.insert(0, headers)

    result_lines: list[str] = []

    # 접두사 텍스트 보존
    prefix = "\n".join(prefix_lines).strip()
    if prefix:
        result_lines.append(prefix)

    if kv_table:
        # 2열 key-value: 각 행의 첫 셀을 key, 두 번째를 value로
        for row in data_rows:
            key = row[0] if len(row) > 0 else ""
            val = row[1] if len(row) > 1 else ""
            if key and val:
                result_lines.append(f"{key}: {val}")
            elif key:
                result_lines.append(key)
            elif val:
                result_lines.append(val)
    elif placeholder:
        # 플레이스홀더 헤더: 값만 콤마로 연결
        for row in data_rows:
            values = [v for v in row if v]
            if values:
                result_lines.append(", ".join(values))
    else:
        # 다열 테이블: "header: value" 쌍을 콤마로 연결
        for row in data_rows:
            pairs: list[str] = []
            for j, val in enumerate(row):
                if not val:
                    continue
                if j < len(headers) and headers[j]:
                    pairs.append(f"{headers[j]}: {val}")
                else:
                    pairs.append(val)
            if pairs:
                result_lines.append(", ".join(pairs))

    return "\n".join(result_lines)


def flatten_tables_in_text(text: str) -> str:
    """텍스트 내 모든 마크다운 테이블을 찾아서 평탄화한다.

    테이블 블록(연속된 |..| 행)을 감지하여 flatten_table()로 변환하고,
    일반 텍스트는 그대로 보존한다.

    Args:
        text: 마크다운 테이블이 포함된 전체 텍스트.

    Returns:
        모든 테이블이 자연어로 변환된 텍스트.
    """
    lines = text.split("\n")
    result_parts: list[str] = []
    table_block: list[str] = []
    # 테이블 직전의 비테이블 텍스트(제목 등) — 짧으면 테이블에 병합
    pending_prefix: list[str] = []

    def _flush_table():
        """누적된 테이블 블록을 평탄화하여 결과에 추가."""
        if not table_block:
            if pending_prefix:
                result_parts.extend(pending_prefix)
                pending_prefix.clear()
            return

        # pending_prefix를 테이블 앞에 붙여서 평탄화
        full_block = "\n".join(pending_prefix + table_block)
        pending_prefix.clear()
        flattened = flatten_table(full_block)
        result_parts.append(flattened)
        table_block.clear()

    for line in lines:
        stripped = line.strip()
        is_table_line = bool(_TABLE_ROW_RE.match(stripped))

        if is_table_line:
            table_block.append(line)
        else:
            if table_block:
                # 테이블 블록이 끝남
                _flush_table()
                result_parts.append(line)
            else:
                # 아직 테이블 시작 전 — 짧은 라인은 다음 테이블의 접두사 후보
                if stripped and len(stripped) < 80:
                    pending_prefix.append(line)
                else:
                    if pending_prefix:
                        result_parts.extend(pending_prefix)
                        pending_prefix.clear()
                    result_parts.append(line)

    # 마지막에 남은 블록 처리
    if table_block:
        _flush_table()
    if pending_prefix:
        result_parts.extend(pending_prefix)

    return "\n".join(result_parts)
