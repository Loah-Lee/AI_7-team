"""텍스트 클리닝 모듈.

한국 RFP 문서 특유의 노이즈(불릿 기호, Bold markdown, 반복 머리말 등)를
정규화하여 임베딩 품질을 높인다.

적용 순서:
0. (PDF only) 마크다운 테이블 → 자연어 평탄화
1. 불릿 기호 정규화 (○□❍ → "- ")
2. Bold markdown 제거 (**text** → text)
3. Heading markdown 제거 (## text → text)
4. 수평선 제거 (HWP only)
5. 반복 머리말/꼬리말 제거
6. 공백 정규화
"""

from __future__ import annotations

import re

from langchain_core.documents import Document

from src.parsers.table_flattener import flatten_tables_in_text

# ── 1. 불릿 기호 정규화 ──────────────────────────────────────────
# 한국 RFP에서 자주 쓰이는 불릿 기호 → "- "로 변환 (리스트 의미 보존)
_BULLET_RE = re.compile(
    r"^(\s*)[○□❍❏◎◇▶▷►●■★☆◆▪▸ｏ]\s*",
    re.MULTILINE,
)
# PDF 파서가 불릿 기호를 backtick으로 감싸는 경우: `❏`, `❍` 등
_BACKTICK_BULLET_RE = re.compile(
    r"^(\s*)`[○□❍❏◎◇▶▷►●■★☆◆▪▸ｏ]`\s*",
    re.MULTILINE,
)

# ── 2. Bold markdown 제거 ────────────────────────────────────────
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# ── 3. Heading markdown 제거 ────────────────────────────────────
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)

# ── 4. 수평선 (HWP only) ────────────────────────────────────────
_HORIZONTAL_RULE_RE = re.compile(r"^[ \t]*[-_=]{3,}[ \t]*$", re.MULTILINE)

# ── 5. 반복 머리말/꼬리말 ───────────────────────────────────────
_HEADER_FOOTER_PATTERNS = [
    # 독립 페이지 번호: "- 3 -", "3/10", "3 / 10", "3", 등
    re.compile(r"^[ \t]*-?\s*\d{1,4}\s*-?[ \t]*$", re.MULTILINE),
    re.compile(r"^[ \t]*\d{1,4}\s*/\s*\d{1,4}[ \t]*$", re.MULTILINE),
    # 일반적인 머리말/꼬리말 키워드
    re.compile(r"^[ \t]*제\s*안\s*요\s*청\s*서[ \t]*$", re.MULTILINE),
    re.compile(r"^[ \t]*\(?\s*비\s*밀\s*\)?\s*$", re.MULTILINE),
]

# ── 6. 공백 정규화 ──────────────────────────────────────────────
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)

def clean_text(text: str, file_type: str = "pdf") -> str:
    """단일 텍스트 블록을 클리닝한다.

    Args:
        text: 원본 텍스트.
        file_type: "pdf" 또는 "hwp". HWP만 수평선 제거 적용.

    Returns:
        클리닝된 텍스트.
    """
    # 0. PDF 전용: 마크다운 테이블 → 자연어 평탄화
    if file_type.lower() == "pdf":
        text = flatten_tables_in_text(text)

    result = text

    # 1. 불릿 기호 정규화
    result = _BULLET_RE.sub(r"\1- ", result)
    result = _BACKTICK_BULLET_RE.sub(r"\1- ", result)

    # 2. Bold markdown 제거
    result = _BOLD_RE.sub(r"\1", result)

    # 3. Heading markdown 제거
    result = _HEADING_RE.sub("", result)

    # 4. 수평선 제거 (HWP only — PDF는 테이블 구분선 보존)
    if file_type.lower() == "hwp":
        # 테이블 행이 아닌 수평선만 제거
        result = _HORIZONTAL_RULE_RE.sub("", result)

    # 5. 반복 머리말/꼬리말 제거
    for pattern in _HEADER_FOOTER_PATTERNS:
        result = pattern.sub("", result)

    # 6. 공백 정규화
    result = result.replace("\t", "    ")  # 탭 → 4 spaces
    result = _TRAILING_WS_RE.sub("", result)
    result = _MULTI_BLANK_RE.sub("\n\n", result)
    result = result.strip()

    return result


def clean_documents(documents: list[Document]) -> list[Document]:
    """Document 리스트 전체를 클리닝한다.

    각 Document의 page_content를 clean_text()로 처리한다.
    file_type 메타데이터를 참조하여 PDF/HWP 조건 분기.
    클리닝 후 빈 문서는 제거한다.

    Args:
        documents: 원본 Document 리스트.

    Returns:
        클리닝된 Document 리스트 (빈 문서 제외).
    """
    cleaned: list[Document] = []
    for doc in documents:
        file_type = doc.metadata.get("file_type", "pdf")
        cleaned_text = clean_text(doc.page_content, file_type)
        if cleaned_text:
            cleaned.append(
                Document(
                    page_content=cleaned_text,
                    metadata=dict(doc.metadata),
                )
            )
    return cleaned
