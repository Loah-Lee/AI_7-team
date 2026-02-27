"""PDF 문서 로더 (pymupdf4llm + fitz 교차 검증).

pymupdf4llm의 to_markdown(page_chunks=True)를 사용하여
테이블 구조를 Markdown 형식으로 보존한다.

pymupdf4llm이 장식 이미지 근처 텍스트를 누락하는 경우,
fitz raw extraction으로 교차 검증하여 큰-폰트 섹션 헤더를 복원한다.
"""

from __future__ import annotations

import fitz
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import List, Tuple

from langchain_core.documents import Document



# 한국어 PDF 추출 플래그 (HWP→PDF 변환 문서 최적화)
# - TEXT_INHIBIT_SPACES (64): CJK 자간 공백 삽입 억제
# - TEXT_USE_CID_FOR_UNKNOWN_UNICODE (8): 미매핑 글리프를 U+FFFD 대신 CID로
# - TEXT_PRESERVE_LIGATURES (1): 합자 보존 (fi, fl 등)
# - TEXT_PRESERVE_WHITESPACE (2): 공백 보존
# - TEXT_MEDIABOX_CLIP (4): 페이지 경계 클리핑
KOREAN_EXTRACT_FLAGS = (
    fitz.TEXT_PRESERVE_LIGATURES
    | fitz.TEXT_PRESERVE_WHITESPACE
    | fitz.TEXT_MEDIABOX_CLIP
    | fitz.TEXT_USE_CID_FOR_UNKNOWN_UNICODE
    | fitz.TEXT_INHIBIT_SPACES
)

# 연속 bold 병합: **A** **B** → **A B** (한 줄에서 반복 적용)
_CONSECUTIVE_BOLD_RE = re.compile(r'\*\*(.+?)\*\*\s*\*\*(.+?)\*\*')

# U+FFFD (고스트 문자) 공백 복원: HWP→PDF 변환 시 공백 글리프 미매핑 현상
# 한글/영문 사이의 FFFD를 공백으로 복원 (컨텍스트 기반)
_FFFD_SPACE_RE = re.compile(r'(?<=[\uAC00-\uD7A3A-Za-z0-9])\uFFFD(?=[\uAC00-\uD7A3A-Za-z0-9])')

def _merge_consecutive_bold(text: str) -> str:
    """한 줄 내에서 연속된 bold 마크다운을 하나로 병합.

    '**Ⅰ** **사업개요**' → '**Ⅰ 사업개요**'
    '**제** **1** **장** **총칙**' → '**제 1 장 총칙**'

    pymupdf4llm이 같은 시각적 줄의 bold 텍스트를 개별 span으로
    분리 출력하는 문제를 해결한다.
    """
    lines = text.split('\n')
    merged: List[str] = []
    for line in lines:
        prev = None
        while prev != line:
            prev = line
            line = _CONSECUTIVE_BOLD_RE.sub(r'**\1 \2**', line)
        merged.append(line)
    return '\n'.join(merged)

_ROMAN_PREFIX_RE = re.compile(
    r"^([IVXivxⅠ-Ⅻⅰ-ⅻ]+)\s+(.+)",
)


def _normalize_section_header(text: str) -> str:
    """로마자 섹션 헤더에 점이 없으면 추가.

    'I 사업 개요'  → 'I. 사업 개요'
    'Ⅳ 제안요청 내용' → 'Ⅳ. 제안요청 내용'
    """
    m = _ROMAN_PREFIX_RE.match(text)
    if m:
        return f"{m.group(1)}. {m.group(2)}"
    return text


def _recover_dropped_headers(
    fitz_doc,
    page_num: int,
    llm_text: str,
) -> List[str]:
    """fitz raw text에서 pymupdf4llm이 누락한 큰-폰트 텍스트를 복원.

    pymupdf4llm이 장식 이미지 근처 텍스트 블록을 드롭하는 문제에 대한 교차 검증.
    같은 시각적 줄(y 좌표 ±3pt)에 있는 큰-폰트 텍스트는 한 덩어리로 처리.
    """
    page = fitz_doc[page_num - 1]  # fitz: 0-indexed
    blocks = page.get_text("dict", flags=KOREAN_EXTRACT_FLAGS, sort=True)["blocks"]

    # 1. 페이지 전체 폰트 크기 수집 → 본문 크기 추정
    all_sizes: List[float] = []
    for b in blocks:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                if span["text"].strip():
                    all_sizes.append(span["size"])

    if not all_sizes:
        return []

    body_size = Counter(round(s, 1) for s in all_sizes).most_common(1)[0][0]
    header_threshold = body_size + 2.0

    # 2. 큰-폰트 라인 수집 (y_center, x, text)
    large_lines: List[Tuple[float, float, str]] = []
    for b in blocks:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            max_size = max(s["size"] for s in spans)
            if max_size < header_threshold:
                continue
            line_text = "".join(s["text"] for s in spans).strip()
            if not line_text:
                continue
            bbox = line["bbox"]
            y_center = (bbox[1] + bbox[3]) / 2
            large_lines.append((y_center, bbox[0], line_text))

    if not large_lines:
        return []

    # 3. y좌표 기준 그룹핑 (같은 시각적 줄 = ±3pt → 한 덩어리)
    large_lines.sort(key=lambda s: (s[0], s[1]))
    groups: List[List[Tuple[float, float, str]]] = []
    for y, x, t in large_lines:
        if groups and abs(y - groups[-1][0][0]) < 3.0:
            groups[-1].append((y, x, t))
        else:
            groups.append([(y, x, t)])

    # 4. pymupdf4llm 출력과 비교, 누락분만 복원
    llm_normalized = re.sub(r"\*\*(.+?)\*\*", r"\1", llm_text)
    llm_normalized = llm_normalized.replace(" ", "")

    recovered: List[str] = []
    for group in groups:
        group.sort(key=lambda s: s[1])
        combined = " ".join(t for _, _, t in group).strip()


        if re.match(r"^-?\s*\d{1,4}\s*-?$", combined):
            continue


        combined_clean = combined.replace(" ", "")
        if combined_clean in llm_normalized:
            continue


        combined = _normalize_section_header(combined)
        recovered.append(combined)

    return recovered


def _clean_fffd_artifacts(text: str) -> str:
    """HWP→PDF 변환 시 발생하는 U+FFFD 공백 아티팩트 제거.

    원인: 폰트 subset embedding 후 ToUnicode CMap이 불완전하면
    공백 글리프가 미매핑되어 U+FFFD (replacement character)로 치환됨.

    해결: 한글/영문/숫자 사이의 FFFD는 공백으로 복원.
    """
    # 카텍스트 기반 복원 (단어 경계에서만 치환)
    text = _FFFD_SPACE_RE.sub(' ', text)
    return text


def _recover_table_content(fitz_doc, page_num: int, llm_text: str) -> str:
    """pymupdf4llm 테이블 변환 후 손실된 테이블 콘텐츠 복원.
    
    경우에 따라 pymupdf4llm이 테이블을 마크다운으로 변환할 때
    구조화된 정보를 손실하거나 파편화하는 경우가 있다.
    fitz의 find_tables()로 직접 추출하여 보완한다.
    """
    page = fitz_doc[page_num - 1]
    
    # 테이블 찾기
    table_finder = page.find_tables()
    recovered_lines = []
    
    for table in table_finder:
        content = table.extract()
        if not content:
            continue
        
        # 테이블의 각 행을 문자열로 변환
        for row in content:
            # None 값과 빈 셀 제거, 공백 정규화
            cells = [str(cell).strip() for cell in row if cell and str(cell).strip()]
            if cells:
                line_text = " ".join(cells)
                # 이미 있는 텍스트와 중복되지 않으면 추가
                if line_text not in llm_text and len(line_text) > 5:
                    recovered_lines.append(line_text)
    
    # 복원된 테이블 라인을 원본 텍스트에 추가
    if recovered_lines:
        return llm_text + "\n\n[테이블에서 추출]\n" + "\n".join(recovered_lines)
    
    return llm_text


def load_pdf(file_path: str | Path) -> list[Document]:
    """PDF 파일을 로드하여 LangChain Document 리스트로 반환한다.

    pymupdf4llm으로 Markdown 변환 후, fitz raw extraction으로
    교차 검증하여 누락된 섹션 헤더를 복원한다.

    Args:
        file_path: PDF 파일 경로.

    Returns:
        페이지별 Document 리스트.
    """
    # Step 0: PyMuPDF 플래그 설정 (한국어 최적화)
    import pymupdf4llm

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    # Step 1: pymupdf4llm으로 마크다운 변환 (테이블 구조 보존)
    page_chunks = pymupdf4llm.to_markdown(
        str(file_path),
        page_chunks=True,
        show_progress=False,
    )

    # Step 2: fitz 교차 검증용 문서 열기
    fitz_doc = fitz.open(str(file_path))
    source_name = unicodedata.normalize("NFC", file_path.name)
    documents: list[Document] = []

    for chunk in page_chunks:  # pymupdf4llm returns untyped dicts
        text = chunk["text"].strip()  # type: ignore
        page_num = chunk["metadata"]["page"]  # type: ignore
        # Step 3: U+FFFD 공백 아티팩트 제거 (HWP→PDF 변환 버그)
        text = _clean_fffd_artifacts(text)

        # Step 4: 연속 bold 병합: **A** **B** → **A B** (헤더 정규화 전에 실행)
        text = _merge_consecutive_bold(text)

        # Step 5: fitz로 누락된 큰-폰트 헤더 복원
        recovered = _recover_dropped_headers(fitz_doc, page_num, text)
        if recovered:
            header_block = "\n\n".join(recovered)
            text = header_block + "\n\n" + text if text else header_block
        if not text:
            continue


        # Step 5.5: 테이블에서 누락된 콘텐츠 복원
        text = _recover_table_content(fitz_doc, page_num, text)

        # Step 6: 정규화 (연속 빈줄, 페이지 번호 제거)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"^\s*-?\s*\d{1,3}\s*-?\s*$", "", text, flags=re.MULTILINE)
        text = text.strip()

        if not text:
            continue

        documents.append(
            Document(
                page_content=text,
                metadata={
                    "source": source_name,
                    "file_type": "pdf",
                    "page": page_num,
                },
            )
        )

    fitz_doc.close()
    return documents
