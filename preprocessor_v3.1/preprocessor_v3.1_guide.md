# preprocessor_v3.1 사용 가이드

한국 RFP 문서 처리 파이프라인 — 완전 참조 문서

---

## 목차

1. [개요](#1-개요)
2. [사전 요구사항](#2-사전-요구사항)
3. [디렉터리 구조](#3-디렉터리-구조)
4. [파이프라인 데이터 흐름](#4-파이프라인-데이터-흐름)
5. [파일별 상세 설명](#5-파일별-상세-설명)
   - 5.1 [hwp_converter.py — HWP→PDF 변환기](#51-hwp_converterpy--hwppdf-변환기)
   - 5.2 [pdf_loader.py — PDF 로더](#52-pdf_loaderpy--pdf-로더)
   - 5.3 [auditor_step2.py — 텍스트 감사기](#53-auditor_step2py--텍스트-감사기)
   - 5.4 [chunker_step4.py — 청킹 파이프라인](#54-chunker_step4py--청킹-파이프라인)
   - 5.5 [storage_step5.py — ChromaDB 하이브리드 저장소](#55-storage_step5py--chromadb-하이브리드-저장소)
   - 5.6 [text_cleaner.py — 텍스트 클리닝 유틸리티](#56-text_cleanerpy--텍스트-클리닝-유틸리티)
   - 5.7 [table_flattener.py — 테이블 평탄화기](#57-table_flattenerpy--테이블-평탄화기)
   - 5.8 [preprocessor.py — 파이프라인 오케스트레이터](#58-preprocessorpy--파이프라인-오케스트레이터)
6. [설정 상수 참조](#6-설정-상수-참조)
7. [CLI 사용 예시](#7-cli-사용-예시)
8. [프로그래밍 방식 사용 예시](#8-프로그래밍-방식-사용-예시)

---

## 1. 개요

`preprocessor_v3.1`은 한국 RFP(제안요청서) 문서를 RAG(Retrieval-Augmented Generation) 시스템에 적합한 형태로 변환하는 전처리 파이프라인이다. HWP 또는 PDF 형식의 원본 문서를 입력받아 ChromaDB 하이브리드 벡터 데이터베이스에 색인하는 전 과정을 자동화한다.

파이프라인의 핵심 설계 원칙:

- **적응형 폰트 프로파일링**: 파일별로 본문 폰트 크기를 동적으로 추정하여 헤더를 감지한다. 하드코딩된 임계값을 사용하지 않는다.
- **TOC 기반 헤딩 매핑**: 목차(TOC) 페이지를 파싱하여 문서별 헤딩 타입과 계층 레벨의 관계를 자동으로 학습한다.
- **하이브리드 검색 지원**: Dense 벡터(SRoBERTa)와 Sparse 벡터(BM25)를 동시에 저장하여 의미 검색과 키워드 검색을 모두 지원한다.

---

## 2. 사전 요구사항

### Python 환경

- **Python 3.10** (conda 환경 `langc` 사용)
- conda 환경 활성화: `conda activate langc`
- 스크립트 실행: `conda run -n langc python3 <script>`

### 시스템 의존성

- **LibreOffice** — HWP 파일을 PDF로 변환할 때 필요하다. HWP 파일을 처리하지 않는다면 설치하지 않아도 된다.
  - Ubuntu/Debian: `sudo apt-get install libreoffice`
  - 지원 경로: `/usr/bin/libreoffice`, `/usr/bin/soffice`, `/opt/libreoffice/program/soffice`

### Python 패키지

```bash
pip install -r requirements.txt
```

주요 패키지 목록:

| 패키지 | 용도 |
|---|---|
| `PyMuPDF` (fitz) | PDF 원시 텍스트 추출 및 폰트 분석 |
| `pymupdf4llm` | PDF → Markdown 변환 (테이블 구조 보존) |
| `langchain`, `langchain-text-splitters` | Document 객체, MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter |
| `chromadb` | 벡터 데이터베이스 (Dense + Sparse 하이브리드) |
| `sentence-transformers` | `jhgan/ko-sroberta-multitask` 임베딩 모델 |
| `kiwipiepy` | 한국어 형태소 분석 (명사 추출, 문장 분리) |

### 환경 변수 (.env)

전처리 파이프라인 자체는 OpenAI API 키가 필요하지 않다. 다운스트림 RAG 파이프라인에서 필요한 키는 별도로 설정한다.

---

## 3. 디렉터리 구조

```
preprocessor_v3.1/
├── preprocessor.py          # 파이프라인 오케스트레이터 (메인 진입점)
├── pdf_loader.py            # PDF 로더 (pymupdf4llm + fitz 교차 검증)
├── auditor_step2.py         # 텍스트 감사기 (TOC 감지, 헤더 삽입)
├── chunker_step4.py         # 7단계 청킹 파이프라인
├── storage_step5.py         # ChromaDB 하이브리드 저장소
├── text_cleaner.py          # 텍스트 클리닝 유틸리티
├── table_flattener.py       # 마크다운 테이블 → 자연어 변환
├── output/
│   ├── temp_pdf/            # HWP 변환 PDF 및 원본 PDF 복사본
│   ├── step1_parsed_*.md    # PDF 로더 출력 (마크다운)
│   ├── step2_audited_*.md   # 감사기 출력 (정제된 마크다운)
│   ├── chunks/              # 청커 출력 (JSON 파일)
│   └── execution_summary.csv
└── DB/
    └── chroma_db/           # ChromaDB 영구 저장소

# 프로젝트 루트 (preprocessor_v3.1/ 상위)
hwp_converter.py             # HWP→PDF 변환기
data/                        # 원본 HWP/PDF 문서 (git 제외)
```

---

## 4. 파이프라인 데이터 흐름

### 전체 흐름도

```
data/*.hwp
    |
    | [hwp_converter.py]
    | LibreOffice headless 변환
    v
output/temp_pdf/*.pdf  <-- data/*.pdf (직접 복사)
    |
    | [pdf_loader.py]
    | pymupdf4llm.to_markdown() + fitz 교차 검증
    | 누락 헤더 복원, 페이지 마커 삽입
    v
output/step1_parsed_*.md
    (YAML frontmatter + <<PAGE: N>> 마커 포함)
    |
    | [auditor_step2.py]
    | Loop 1: TOC 페이지 감지
    | Selection Stage: TOC bold/non-bold → type→level 매핑
    | Loop 2: 본문 헤더 삽입 (#/##)
    v
output/step2_audited_*.md
    (TOC 중립화 + 본문 #/## 헤더 삽입 완료)
    |
    | [chunker_step4.py]
    | Step 2: 테이블 평탄화
    | Step 2b: 텍스트 클리닝
    | Step 3: 정규식 계층 추출 (auditor가 처리하지 않은 타입 포함)
    | Step 4: 헤더 삽입
    | Step 5: 페이지 마커 변환
    | Step 6: MarkdownHeaderTextSplitter
    | Step 7: RecursiveCharacterTextSplitter
    v
output/chunks/chunk_*.json
    (청크별 JSON: page_content + metadata)
    |
    | [storage_step5.py]
    | compute_doc_id → assign_uids → build_hierarchy
    | upsert_hybrid_chunks (Dense SRoBERTa + Sparse BM25)
    | upsert_hierarchy_chroma
    v
DB/chroma_db/
    ├── chunks 컬렉션    (Dense + Sparse 하이브리드)
    └── hierarchy 컬렉션 (Dense 전용, L1/L2 섹션 요약)
```

### 중간 파일 형식

**step1_parsed_*.md** (pdf_loader 출력):
```markdown
---
document_title: "문서제목"
source_file: "원본파일명.pdf"
total_pages: 42
---

<<PAGE: 1>>

# I. 사업 개요

본 사업은 ...
```

**step2_audited_*.md** (auditor 출력):
- TOC 페이지 내용이 2칸 들여쓰기로 중립화됨
- 본문의 TOC 매핑 헤딩 타입에 `#` 또는 `##` 접두사 삽입됨

**output/chunks/chunk_*.json** (chunker 출력):
```json
{
  "chunk_id": 0,
  "doc_id": "a1b2c3d4e5f6g7h8",
  "uid": "a1b2c3d4e5f6g7h8_0",
  "page_content": "청크 텍스트 내용...",
  "metadata": {
    "document_title": "문서제목",
    "source": "원본파일명.pdf",
    "section_level1": "I. 사업 개요",
    "section_level2": "N/A",
    "page_start": 3,
    "page_end": 5,
    "institution": "기관명",
    "project_name": "사업명",
    "chunk_size": 487,
    "created_at": "2026-02-24T10:30:00.000000"
  }
}
```

---

## 5. 파일별 상세 설명

---

### 5.1 `hwp_converter.py` — HWP→PDF 변환기

**위치**: 프로젝트 루트 (`preprocessor_v3.1/` 상위 디렉터리)

**목적**: LibreOffice headless 모드를 사용하여 HWP/HWPX 파일을 PDF로 변환한다. 한글 파일명과 특수 기호가 포함된 경로를 안전하게 처리한다.

#### 클래스: `HWPConverter`

```python
class HWPConverter:
    def __init__(self)
    def convert(self, hwp_path: str, output_dir: str = None) -> dict
```

**`__init__(self)`**

초기화 시 LibreOffice 실행 파일 경로를 자동으로 탐색한다. 탐색 순서:
1. `/usr/bin/libreoffice`
2. `/usr/bin/soffice`
3. `/opt/libreoffice/program/soffice`
4. `which libreoffice` (PATH 검색)
5. `which soffice` (PATH 검색)

LibreOffice를 찾지 못하면 `FileNotFoundError`를 발생시킨다.

**`convert(self, hwp_path: str, output_dir: str = None) -> dict`**

HWP 파일을 PDF로 변환한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `hwp_path` | `str` | 변환할 HWP/HWPX 파일 경로 |
| `output_dir` | `str` (선택) | PDF 저장 디렉터리. 미지정 시 입력 파일과 같은 디렉터리 |

반환값 (`dict`):
```python
{
    'success': True,
    'input_file': '/절대/경로/파일.hwp',
    'output_file': '/절대/경로/파일.pdf',
    'size': 1234567  # 바이트 단위
}
```

내부 동작:
- `shell=False`로 LibreOffice를 호출하여 파일명의 특수 기호가 쉘에 의해 해석되지 않도록 한다.
- `LANG=ko_KR.UTF-8` 환경 변수를 설정하여 인코딩 문제를 방지한다.
- 변환 제한 시간은 300초(5분)이다.
- LibreOffice가 점이 여러 개인 파일명에서 마지막 확장자만 교체하는 동작을 처리한다.

오류 처리:
- 파일 없음: `FileNotFoundError`
- LibreOffice 오류: `RuntimeError`
- 시간 초과: `RuntimeError("변환 시간 초과")`

---

### 5.2 `pdf_loader.py` — PDF 로더

**목적**: pymupdf4llm으로 PDF를 마크다운으로 변환하고, fitz raw extraction으로 교차 검증하여 장식 이미지 근처에서 누락된 섹션 헤더를 복원한다.

#### 상수

| 상수 | 값 | 설명 |
|---|---|---|
| `_ROMAN_PREFIX_RE` | `re.compile(r"^([IVXivxⅠ-Ⅻⅰ-ⅻ]+)\s+(.+)")` | 로마 숫자 접두사 감지 정규식 |

#### 함수

**`_normalize_section_header(text: str) -> str`**

로마 숫자 섹션 헤더에 점이 없으면 추가한다.

```python
_normalize_section_header('I 사업 개요')      # → 'I. 사업 개요'
_normalize_section_header('Ⅳ 제안요청 내용')  # → 'Ⅳ. 제안요청 내용'
_normalize_section_header('I. 사업 개요')     # → 'I. 사업 개요' (변경 없음)
```

**`_recover_dropped_headers(fitz_doc, page_num: int, llm_text: str) -> List[str]`**

pymupdf4llm이 장식 이미지 근처에서 누락한 큰 폰트 텍스트를 fitz raw extraction으로 복원한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `fitz_doc` | fitz.Document | 이미 열린 fitz 문서 객체 |
| `page_num` | `int` | 1-indexed 페이지 번호 |
| `llm_text` | `str` | pymupdf4llm이 생성한 해당 페이지 텍스트 |

반환값: 복원된 헤더 텍스트 목록 (`List[str]`)

내부 알고리즘:
1. 페이지 전체 폰트 크기를 수집하여 가장 빈번한 크기를 본문 크기로 추정한다.
2. 본문 크기 + 2.0pt 이상인 텍스트 스팬을 큰 폰트 라인으로 분류한다.
3. y 좌표 기준으로 ±3pt 이내의 스팬을 같은 시각적 줄로 그룹핑한다.
4. pymupdf4llm 출력에 이미 포함된 텍스트는 제외하고, 누락된 것만 반환한다.
5. 페이지 번호 패턴(`-3-`, `3` 등)은 필터링한다.

**`load_pdf(file_path: str | Path) -> list[Document]`**

PDF 파일을 로드하여 LangChain Document 리스트로 반환한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `file_path` | `str` 또는 `Path` | PDF 파일 경로 |

반환값: 페이지별 `Document` 리스트. 각 Document의 `metadata`:
```python
{
    "source": "파일명.pdf",   # NFC 정규화된 파일명
    "file_type": "pdf",
    "page": 3               # 1-indexed 페이지 번호
}
```

내부 동작:
1. `pymupdf4llm.to_markdown(page_chunks=True)`로 페이지별 마크다운 생성
2. `fitz.open()`으로 동일 파일을 한 번 더 열어 교차 검증 (단일 열기, 2패스 아키텍처)
3. 각 페이지에서 `_recover_dropped_headers()`로 누락 헤더 복원
4. 복원된 헤더를 페이지 텍스트 앞에 삽입
5. 3개 이상 연속 줄바꿈을 2개로 정규화
6. 독립 페이지 번호 패턴 제거
7. 빈 페이지는 Document 목록에서 제외

---

### 5.3 `auditor_step2.py` — 텍스트 감사기

**목적**: 파싱된 마크다운을 정제하고, TOC(목차) 페이지를 감지하여 문서별 헤딩 타입과 계층 레벨의 관계를 학습한 뒤, 본문에 `#`/`##` 마크다운 헤더를 삽입한다.

#### 3-루프 아키텍처

감사기는 세 단계로 동작한다:

```
[Loop 1] TOC 페이지 감지
    detect_toc_pages() — 모든 비어 있지 않은 줄이 헤딩 패턴인 연속 페이지 탐색
         |
         v
[Selection Stage] TOC 파싱 → type→level 매핑 생성
    _extract_toc_heading_types() — Bold 항목 → L1, non-bold 항목 → L2
    예: {'roman': 1, 'numbered_d1': 2, 'bracket': 1}
         |
         v
    neutralize_toc() — TOC 페이지 내용을 2칸 들여쓰기로 중립화
         |
         v
[Loop 2] 본문 헤더 삽입
    insert_body_headers() — TOC 매핑에 있는 타입만 #/## 삽입
```

**중요**: `_extract_toc_heading_types()`는 반드시 `neutralize_toc()` 호출 전에 실행해야 한다. 중립화 후에는 원본 TOC 텍스트를 읽을 수 없다.

#### 헤딩 타입 정규식 상수

| 상수명 | 패턴 예시 | 타입명 |
|---|---|---|
| `_H_LEGAL_RE` | `제3장 계약 조건` | `legal` (세부: `제N장`, `제N절` 등) |
| `_H_NUMBERED_D3_RE` | `1.2.3. 세부 항목` | `numbered_d3` |
| `_H_NUMBERED_D2_RE` | `1.2. 중간 항목` | `numbered_d2` |
| `_H_NUMBERED_D1_RE` | `1. 주요 항목` | `numbered_d1` |
| `_H_ROMAN_RE` | `I. 사업 개요` | `roman` |
| `_H_KOREAN_LET_RE` | `가. 세부 내용` | `korean_letter` |
| `_H_BRACKET_RE` | `[별첨] 참고자료` | `bracket` |

```python
LEGAL_ORDER = ["편", "장", "절", "조", "항"]  # 법적 헤딩 계층 순서
SPACING_SAFETY_RATIO = 0.15  # 단어 간격 수정 안전 비율 (15% 초과 변경 시 원본 유지)
```

#### 함수

**`fix_single_char_spacing(text: str) -> str`**

한국어 낱글자 사이의 불필요한 공백을 제거한다. 전체 텍스트 길이 변화가 `SPACING_SAFETY_RATIO`(15%)를 초과하면 원본을 반환하여 과도한 수정을 방지한다.

**`standardize_bullets(text: str) -> str`**

`○`, `●`, `■`, `※`, `◆`, `◇`, `▶`, `▷`, `►` 등의 불릿 기호를 `* `로 표준화한다.

**`merge_table_cell_linebreaks(text: str) -> str`**

테이블 셀 내부에서 줄바꿈으로 분리된 텍스트를 같은 셀 행에 합친다. 다음 줄이 `|`로 시작하지 않고, `#`으로 시작하지 않으며, 페이지 마커가 아닌 경우에만 병합한다.

**`cleanup_whitespace(text: str) -> str`**

연속 공백을 단일 공백으로, 3개 이상 연속 줄바꿈을 2개로 정규화한다.

**`detect_toc_pages(text: str) -> Set[int]`**

TOC 페이지 번호 집합을 반환한다.

판별 기준: 비어 있지 않은 줄이 3개 이상이고, 그 모든 줄이 헤딩 패턴(`_ALL_HEADING_RE`)에 매칭되며, 일반 본문 줄이 0개인 페이지를 TOC로 간주한다. TOC 페이지는 연속되어야 하며, 비-TOC 페이지가 나타나면 탐색을 중단한다.

**`neutralize_toc(text: str, toc_pages: Set[int]) -> str`**

TOC 페이지의 모든 비어 있지 않은 줄(페이지 마커, 테이블 행 제외)에 2칸 들여쓰기를 추가한다. 이렇게 하면 청커의 정규식이 TOC 항목을 헤딩으로 오인하지 않는다.

**`_extract_toc_heading_types(text: str, toc_pages: Set[int]) -> Dict[str, int]`**

TOC 페이지를 파싱하여 헤딩 타입과 계층 레벨의 매핑을 생성한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `text` | `str` | 중립화 전 원본 마크다운 텍스트 |
| `toc_pages` | `Set[int]` | TOC 페이지 번호 집합 |

반환값 예시:
```python
{'roman': 1, 'bracket': 1, 'numbered_d1': 2}
# roman 타입 → L1 (#), numbered_d1 타입 → L2 (##)
```

매핑 규칙:
- `**굵은 글씨**` TOC 항목 → L1 타입
- 일반 TOC 항목 → L2 타입
- L1과 L2에 모두 있는 타입은 L1 우선
- `legal` 타입은 세부 분류(`제N장`, `제N절` 등)로 구분

**`insert_body_headers(text: str, toc_pages: Set[int], toc_type_level: Dict[str, int]) -> str`**

본문에서 TOC 매핑에 해당하는 헤딩 타입에만 `#`(L1) 또는 `##`(L2)를 삽입한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `text` | `str` | 중립화된 마크다운 텍스트 |
| `toc_pages` | `Set[int]` | TOC 페이지 번호 집합 (해당 페이지는 건너뜀) |
| `toc_type_level` | `Dict[str, int]` | `_extract_toc_heading_types()` 반환값 |

동작 조건:
- `toc_type_level`이 비어 있으면 아무것도 삽입하지 않는다.
- 1페이지(표지)는 건너뛴다.
- TOC 페이지는 건너뛴다.
- 이미 `#`으로 시작하는 줄, 테이블 행(`|`), 페이지 마커는 건너뛴다.
- L3 이상은 마크다운 헤더를 삽입하지 않는다.

**`validate_tables(text: str) -> None`**

`|`로 시작하는 줄 수를 출력한다. 반환값 없음, 진단 목적.

**`audit_file(input_path: str, output_path: str) -> None`**

단일 파일에 대한 전체 감사 파이프라인을 실행한다. 메인 진입점.

실행 순서:
1. YAML frontmatter와 본문 분리
2. `_process_body()` — 본문 전체에 텍스트 정제 적용
3. `detect_toc_pages()` — TOC 페이지 감지
4. `_extract_toc_heading_types()` — TOC 파싱 (중립화 전)
5. `neutralize_toc()` — TOC 중립화
6. `insert_body_headers()` — 본문 헤더 삽입
7. `validate_tables()` — 테이블 검증 (진단)
8. 결과 파일 저장

#### 청커와의 협력 관계

감사기와 청커는 헤딩 처리를 분담한다:

- **감사기**: TOC에 명시된 헤딩 타입(`roman`, `numbered_d1` 등)에만 `#`/`##` 삽입
- **청커 Step 3**: 감사기가 처리하지 않은 나머지 타입(`korean_letter`, `legal`, `bracket` 등)을 독립적으로 처리

이 분업 덕분에 TOC가 없는 문서도 청커가 독립적으로 계층 구조를 추출할 수 있다.

---

### 5.4 `chunker_step4.py` — 청킹 파이프라인

**목적**: 감사된 마크다운 파일을 7단계 파이프라인으로 처리하여 RAG에 적합한 크기의 청크로 분할하고 JSON으로 저장한다.

#### 7단계 파이프라인

```
Step 1  parse_frontmatter()     YAML frontmatter 파싱 및 분리
Step 2  step2_flatten_tables()  마크다운 테이블 → 자연어 평탄화
Step 2b step2b_clean_text()     텍스트 클리닝 (파이프라인 안전 기능만)
Step 3  step3_extract_hierarchy() 정규식 계층 구조 추출
Step 4  step4_insert_headers()  레벨별 #/## 헤더 삽입
Step 5  step5_convert_page_markers() <<PAGE:N>> → [[[Page: N]]]
Step 6  step6_markdown_header_split() MarkdownHeaderTextSplitter
Step 7  step7_recursive_split() RecursiveCharacterTextSplitter
```

#### 주요 상수

```python
CHUNK_SIZE = 500     # 최대 청크 크기 (문자 수)
CHUNK_OVERLAP = 100  # 청크 간 겹침 크기 (문자 수)
LEGAL_ORDER = ["편", "장", "절", "조", "항"]  # 법적 헤딩 계층 순서
```

#### 함수

**`parse_frontmatter(text: str) -> Tuple[Dict, str]`**

YAML frontmatter(`---` 블록)를 파싱하여 메타데이터 딕셔너리와 본문을 분리한다.

반환값: `(메타데이터 Dict, 본문 str)`

**`step2_flatten_tables(text: str) -> str`**

`table_flattener.flatten_tables_in_text()`에 위임한다. 마크다운 테이블을 자연어로 변환한다.

**`step2b_clean_text(text: str) -> str`**

파이프라인을 손상시키지 않는 `text_cleaner` 기능만 선별 적용한다.

적용 기능:
- 불릿 기호 정규화 (`_BULLET_RE`, `_BACKTICK_BULLET_RE`)
- Bold 마크다운 제거 (`_BOLD_RE`)
- 반복 머리말/꼬리말 제거 (`_HEADER_FOOTER_PATTERNS`)
- 공백 정규화 (탭 → 4 spaces, trailing whitespace, 연속 빈줄)

적용하지 않는 기능:
- 헤딩 마크다운 제거 — Step 4 헤더 삽입과 충돌
- 수평선 제거 — HWP 전용 (PDF 파이프라인에 불필요)

**`step3_extract_hierarchy(text: str) -> List[Tuple[str, int, int]]`**

정규식으로 섹션 계층 구조를 추출한다. 1페이지(표지)는 건너뛴다.

반환값: `[(헤딩 텍스트, 레벨, 문자 위치), ...]`

레벨 할당 알고리즘:
- **Phase 1 (Group A — 법적 헤딩)**: `편 → 장 → 절 → 조 → 항` 순서로 문서에 존재하는 타입만 순차적으로 레벨 1, 2, 3... 할당
- **Phase 2 (Group B — 나머지)**: 첫 등장 순서대로 다음 레벨 할당. 단, `bracket` 타입은 항상 L1

**`step4_insert_headers(text: str, hierarchy: List[Tuple[str, int, int]]) -> str`**

계층 구조 정보를 바탕으로 마크다운 헤더를 삽입한다.

- 레벨 1 → `# ` 접두사
- 레벨 2 → `## ` 접두사
- 레벨 3 이상 → 마크다운 헤더 없음 (청크 메타데이터에만 반영)

뒤에서부터 삽입하여 앞쪽 문자 위치를 보존한다.

**`step5_convert_page_markers(text: str) -> str`**

`<<PAGE: N>>` 형식의 페이지 마커를 `[[[Page: N]]]` 형식으로 변환한다. MarkdownHeaderTextSplitter가 페이지 마커를 올바른 섹션에 포함시키도록 마커를 헤더 뒤로 재배치하는 내부 함수 `_relocate_page_markers_before_headers()`도 함께 호출된다.

**`step6_markdown_header_split(text: str) -> list`**

LangChain `MarkdownHeaderTextSplitter`로 `#`/`##` 헤더 기준 분할한다.

설정:
```python
headers_to_split_on = [("#", "Header 1"), ("##", "Header 2")]
strip_headers=False  # 헤더 텍스트를 청크 내용에 보존
```

각 Document에 `page_start`, `page_end` 메타데이터를 추가한다. 페이지 마커가 없는 섹션은 이전 섹션의 페이지 번호를 상속한다.

**`step7_recursive_split(docs: list) -> list`**

LangChain `RecursiveCharacterTextSplitter`로 크기 기준 분할한다.

```python
chunk_size=500    # CHUNK_SIZE 상수 사용
chunk_overlap=100 # CHUNK_OVERLAP 상수 사용
```

**`process_file(file_path: Path) -> List[Dict]`**

단일 파일에 대한 전체 7단계 파이프라인을 실행한다. 메인 진입점.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `file_path` | `Path` | 처리할 마크다운 파일 경로 |

반환값: 청크 딕셔너리 목록. 각 딕셔너리 구조:
```python
{
    'page_content': '청크 텍스트',
    'metadata': {
        'document_title': '문서제목',
        'source': '원본파일명.pdf',
        'section_level1': 'I. 사업 개요',
        'section_level2': 'N/A',
        'page_start': 3,
        'page_end': 5,
        'institution': '기관명',
        'project_name': '사업명',
        'chunk_size': 487,
        'created_at': '2026-02-24T10:30:00.000000'
    }
}
```

`institution`과 `project_name`은 파일명이 `기관명_사업명.pdf` 형식일 때 자동으로 분리된다.

**`process_all_files(file_paths: List[Path], output_dir: Path) -> List[Dict]`**

여러 파일을 순차적으로 처리하고 전역 `chunk_id`를 부여하여 JSON 파일로 저장한다.

**`print_statistics(chunks: List[Dict]) -> None`**

청킹 결과 통계(총 청크 수, 총 문자 수, 평균/최소/최대 크기)를 출력한다.

---

### 5.5 `storage_step5.py` — ChromaDB 하이브리드 저장소

**목적**: 청크 JSON 파일을 ChromaDB에 Dense(SRoBERTa) + Sparse(BM25) 하이브리드 벡터로 색인한다. Cloud API 없이 로컬에서 완전히 동작한다.

#### 주요 상수 및 초기화

```python
CHROMA_PATH = "DB/chroma_db"          # ChromaDB 영구 저장 경로
CHUNK_DIR = "output/chunks"           # 청크 JSON 디렉터리
EMBEDDING_MODEL = 'jhgan/ko-sroberta-multitask'  # Dense 임베딩 모델 (768차원)

# BM25 Sparse 임베딩 파라미터
bm25_ef = ChromaBm25EmbeddingFunction(
    k=1.2,              # BM25 term frequency 포화 파라미터
    b=0.75,             # 문서 길이 정규화 파라미터
    avg_doc_length=256.0,  # 평균 문서 길이 (문자 수)
    token_max_length=40    # 최대 토큰 길이
)
```

모듈 로드 시 다음 객체가 초기화된다:
- `_kiwi = Kiwi()` — 한국어 형태소 분석기
- `client = chromadb.PersistentClient(path=CHROMA_PATH)` — ChromaDB 클라이언트
- `dense_ef` — SentenceTransformer 임베딩 함수
- `bm25_ef` — BM25 Sparse 임베딩 함수

#### ChromaDB 컬렉션 구조

| 컬렉션명 | 임베딩 | 용도 |
|---|---|---|
| `chunks` | Dense (cosine) + Sparse (BM25, metadata에 JSON 저장) | 청크 하이브리드 검색 |
| `hierarchy` | Dense (cosine) | L1/L2 섹션 요약 검색 |

#### 함수

**`compute_doc_id(parser_raw_path: Path) -> str`**

파일 내용의 SHA-256 해시 앞 16자리를 문서 ID로 반환한다. 동일 파일은 항상 같은 ID를 생성하여 멱등성을 보장한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `parser_raw_path` | `Path` | step1_parsed_*.md 파일 경로 |

반환값: 16자리 16진수 문자열 (예: `"a1b2c3d4e5f6g7h8"`)

**`extract_nouns(text: str) -> str`**

kiwipiepy로 한국어 명사를 추출하여 공백으로 연결된 문자열로 반환한다. BM25 색인 품질 최적화를 위해 일반명사(`NNG`), 고유명사(`NNP`), 의존명사(`NNB`)만 추출한다.

**`_normalize_metadata(metadata: Dict) -> Dict`**

ChromaDB의 타입 제약을 해결한다. `None` 값은 제거하고, `list`/`dict` 값은 JSON 문자열로 직렬화한다.

**`_generate_section_summary(title: str, level: int, relevant_chunks: List[Dict]) -> str`**

계층 검색용 섹션 요약을 생성한다. 해당 섹션의 청크 중 앞 3개를 선택하여 각 청크의 첫 2문장을 추출하고 연결한다. 400자를 초과하면 잘라낸다.

반환 형식: `"[Level 1] 섹션 제목\n요약 텍스트..."`

**`_sparse_to_dict(sparse_vec) -> Dict`**

`ChromaBm25EmbeddingFunction`이 반환하는 SparseVector를 JSON 직렬화 가능한 딕셔너리로 변환한다.

**`assign_uids(chunks: List[Dict]) -> None`**

각 청크에 순차적 UID를 부여한다. 형식: `{doc_id}_{index}` (예: `"a1b2c3d4_0"`, `"a1b2c3d4_1"`). 청크의 `metadata`에 `uid`, `doc_id`, `type`, `chunk_order`를 추가한다. 반환값 없음 (in-place 수정).

**`build_hierarchy(chunks: List[Dict]) -> Tuple[List[Tuple[str, Dict]], Dict]`**

청크 목록에서 L1/L2 계층 엔트리를 생성한다.

반환값:
- `List[Tuple[str, Dict]]`: `(요약 텍스트, 메타데이터)` 쌍 목록
- `Dict`: `{doc_id: {chunk_order: section_uid}}` 매핑

각 L1 섹션과 L2 섹션에 대해 `_generate_section_summary()`로 요약을 생성하고, 고유한 계층 UID(`{doc_id}_h_{n}`)를 부여한다.

**`apply_section_uids(chunks: List[Dict], section_uid_map: Dict) -> None`**

각 청크의 `metadata`에 `section_uid`를 주입한다. 청크가 속한 가장 구체적인 섹션(L2 우선, 없으면 L1)의 UID를 사용한다. 반환값 없음 (in-place 수정).

**`upsert_hybrid_chunks(chunks: List[Dict]) -> int`**

청크를 ChromaDB `chunks` 컬렉션에 하이브리드 벡터로 upsert한다.

동작 순서:
1. 해당 `doc_id`의 기존 항목을 모두 삭제 (재색인 보장)
2. 모든 청크의 명사를 추출하여 BM25 Sparse 벡터 일괄 생성
3. Sparse 벡터를 JSON으로 직렬화하여 `metadata["sparse_embedding"]`에 저장
4. Dense 임베딩은 ChromaDB가 `dense_ef`로 자동 생성
5. `collection.upsert()` 호출

반환값: upsert된 청크 수

**`upsert_hierarchy_chroma(hierarchy_entries: List[Tuple[str, Dict]]) -> int`**

계층 정보를 ChromaDB `hierarchy` 컬렉션에 저장한다. Dense 임베딩만 사용한다. 해당 `doc_id`의 기존 항목을 먼저 삭제한 뒤 upsert한다.

반환값: upsert된 계층 엔트리 수

**`verify_integrity(expected_count: int) -> bool`**

ChromaDB `chunks` 컬렉션의 실제 항목 수와 기대값을 비교하여 무결성을 검증한다.

---

### 5.6 `text_cleaner.py` — 텍스트 클리닝 유틸리티

**목적**: 한국 RFP 문서 특유의 노이즈(불릿 기호, Bold 마크다운, 반복 머리말/꼬리말 등)를 정규화하여 임베딩 품질을 높인다.

#### 내보내는 상수 (chunker가 직접 임포트)

| 상수 | 설명 |
|---|---|
| `_BULLET_RE` | 한국 RFP 불릿 기호 패턴 (`○□❍❏◎◇▶▷►●■★☆◆▪▸ｏ`) |
| `_BACKTICK_BULLET_RE` | PDF 파서가 backtick으로 감싼 불릿 기호 패턴 |
| `_BOLD_RE` | Bold 마크다운 패턴 (`**text**`) |
| `_HEADER_FOOTER_PATTERNS` | 반복 머리말/꼬리말 패턴 목록 (페이지 번호, "제안요청서", "(비밀)" 등) |
| `_MULTI_BLANK_RE` | 3개 이상 연속 줄바꿈 패턴 |
| `_TRAILING_WS_RE` | 줄 끝 공백 패턴 |

#### 함수

**`clean_text(text: str, file_type: str = "pdf") -> str`**

단일 텍스트 블록을 클리닝한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `text` | `str` | 원본 텍스트 |
| `file_type` | `str` | `"pdf"` 또는 `"hwp"`. HWP만 수평선 제거 적용 |

적용 순서:
0. PDF 전용: 마크다운 테이블 → 자연어 평탄화
1. 불릿 기호 정규화 (`○□❍...` → `- `)
2. Bold 마크다운 제거 (`**text**` → `text`)
3. 헤딩 마크다운 제거 (`# `, `## ` 등)
4. 수평선 제거 (HWP 전용)
5. 반복 머리말/꼬리말 제거
6. 공백 정규화 (탭 → 4 spaces, trailing whitespace, 연속 빈줄)

**주의**: `clean_text()`는 헤딩 마크다운을 제거하므로 청커 파이프라인 중간에 직접 호출하면 Step 4에서 삽입한 `#`/`##`가 사라진다. 청커는 `step2b_clean_text()`를 통해 안전한 기능만 선별 적용한다.

**`clean_documents(documents: list[Document]) -> list[Document]`**

Document 리스트 전체를 클리닝한다. 각 Document의 `metadata["file_type"]`을 참조하여 PDF/HWP 조건을 분기한다. 클리닝 후 빈 문서는 결과에서 제외한다.

---

### 5.7 `table_flattener.py` — 테이블 평탄화기

**목적**: PDF 파서가 생성하는 마크다운 테이블(`|Col1|Col2|...`)을 자연어 형태로 변환하여 임베딩 유사도를 높인다.

변환 예시:
```
Before:
| 사업명 | 차세대 포털 |
|---|---|
| 사업기간 | 24개월 |

After:
사업명: 차세대 포털
사업기간: 24개월
```

#### 내부 상수

| 상수 | 설명 |
|---|---|
| `_TABLE_ROW_RE` | 마크다운 테이블 행 패턴 (`|`로 시작하고 끝남) |
| `_TABLE_SEP_RE` | 구분선 행 패턴 (`|---|---|`) |
| `_PLACEHOLDER_HEADER_RE` | 플레이스홀더 헤더 패턴 (`Col1`, `Column2` 등) |
| `_GENERIC_KV_HEADERS` | 의미 없는 일반 열 제목 집합 (`{"항목", "내용", "구분", "설명", "비고", "분류", "세부내용"}`) |
| `_BR_TAG_RE` | `<br>` 태그 패턴 |

#### 함수

**`flatten_table(table_text: str) -> str`**

단일 마크다운 테이블을 자연어 텍스트로 변환한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `table_text` | `str` | 마크다운 테이블 텍스트 (앞에 섹션 제목 포함 가능) |

변환 규칙:
- **2열 key-value 테이블**: `"key: value"` 형식으로 행별 출력
- **다열 테이블**: `"header1: val1, header2: val2"` 형식으로 행별 출력
- **플레이스홀더 헤더** (`Col1`, `Col2`): 헤더 없이 값만 콤마로 연결
- **일반 KV 헤더** (`항목`, `내용` 등): 헤더 행도 데이터로 처리
- 테이블 앞의 섹션 제목 등 비테이블 텍스트는 보존

**`flatten_tables_in_text(text: str) -> str`**

텍스트 내 모든 마크다운 테이블을 찾아서 평탄화한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `text` | `str` | 마크다운 테이블이 포함된 전체 텍스트 |

80자 미만의 짧은 비테이블 줄은 다음 테이블의 접두사 후보로 처리하여 섹션 제목과 테이블을 함께 평탄화한다. 일반 텍스트는 그대로 보존한다.

---

### 5.8 `preprocessor.py` — 파이프라인 오케스트레이터

**목적**: `data/` 디렉터리의 HWP/PDF 파일을 스캔하여 전체 파이프라인(로더 → 감사기 → 청커 → 저장소)을 순차적으로 실행하고 실행 요약 CSV를 생성한다.

#### 주요 상수

```python
ABSOLUTE_TIME_THRESHOLD = 60.0    # 처리 시간 절대 임계값 (초). 샘플 수 부족 시 사용
DYNAMIC_TIME_MULTIPLIER = 3.0     # 동적 임계값 배수 (평균의 3배 초과 시 이상 감지)
DYNAMIC_MIN_SAMPLES = 10          # 동적 임계값 적용 최소 샘플 수
```

#### 함수

**`_documents_to_parsed_markdown(docs: list, source_name: str, output_path: Path) -> None`**

`pdf_loader.load_pdf()`가 반환한 Document 리스트를 `<<PAGE: N>>` 마커가 포함된 마크다운 파일로 변환한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `docs` | `list` | `load_pdf()` 반환 Document 리스트 |
| `source_name` | `str` | 원본 파일명 (YAML frontmatter에 기록) |
| `output_path` | `Path` | 출력 마크다운 파일 경로 |

출력 파일 형식:
```markdown
---
document_title: "파일명"
source_file: "원본파일명.pdf"
total_pages: 42
---

<<PAGE: 1>>

페이지 내용...
```

**`process_single_pdf(pdf_path: Path, output_dir: Path) -> Dict`**

단일 PDF 파일에 대한 전체 파이프라인을 실행한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `pdf_path` | `Path` | 처리할 PDF 파일 경로 |
| `output_dir` | `Path` | 중간 파일 저장 디렉터리 |

반환값 (`Dict`):
```python
{
    'file': '파일명.pdf',
    'status': 'success',      # 또는 'failed'
    'duration_sec': 12.3,
    'chunk_count': 87,
    'sparse_count': 87,       # upsert된 Sparse 벡터 수
    'dense_count': 87,        # upsert된 Dense 벡터 수
    'hierarchy_count': 12,    # upsert된 계층 엔트리 수
    'reindexed': True,
    'error': ''               # 실패 시 오류 메시지
}
```

실행 순서:
1. `load_pdf()` → `_documents_to_parsed_markdown()` → `step1_parsed_{stem}.md`
2. `audit_file()` → `step2_audited_{stem}.md`
3. `process_file()` → 청크 목록
4. 청크별 JSON 파일 저장 (`output/chunks/chunk_{stem}_{i:05d}.json`)
5. `assign_uids()` → `build_hierarchy()` → `apply_section_uids()`
6. `upsert_hybrid_chunks()` → `upsert_hierarchy_chroma()`

청크가 0개이면 `status: 'failed'`를 반환한다.

**`check_time_anomaly(duration: float, history: List[float]) -> bool`**

처리 시간 이상을 감지한다.

| 매개변수 | 타입 | 설명 |
|---|---|---|
| `duration` | `float` | 현재 파일 처리 시간 (초) |
| `history` | `List[float]` | 이전 파일들의 처리 시간 목록 |

판별 로직:
- `history` 길이 < `DYNAMIC_MIN_SAMPLES`(10): `duration > ABSOLUTE_TIME_THRESHOLD`(60초)
- `history` 길이 >= 10: `duration > 평균 * DYNAMIC_TIME_MULTIPLIER`(3.0배)

**`write_summary(results: List[Dict], output_path: Path) -> None`**

처리 결과를 CSV 파일로 저장한다. 컬럼: `file`, `status`, `duration_sec`, `chunk_count`, `sparse_count`, `dense_count`, `hierarchy_count`, `reindexed`, `error`.

#### CLI 동작 (`__main__`)

1. `data/` 디렉터리 스캔
2. `.hwp` 파일: `hwp_converter.py`로 PDF 변환 후 `output/temp_pdf/`에 저장
3. 기타 파일: `output/temp_pdf/`에 직접 복사
4. `output/temp_pdf/*.pdf` 전체를 `process_single_pdf()`로 순차 처리
5. 처리 시간 이상 감지 및 경고 출력
6. `output/execution_summary.csv` 저장

---

## 6. 설정 상수 참조

파이프라인 동작을 조정할 때 수정하는 상수 목록이다.

### preprocessor.py

| 상수 | 기본값 | 설명 |
|---|---|---|
| `ABSOLUTE_TIME_THRESHOLD` | `60.0` | 처리 시간 절대 임계값 (초). 샘플 10개 미만일 때 사용 |
| `DYNAMIC_TIME_MULTIPLIER` | `3.0` | 동적 이상 감지 배수 (평균의 N배 초과 시 경고) |
| `DYNAMIC_MIN_SAMPLES` | `10` | 동적 임계값 전환 최소 샘플 수 |

### auditor_step2.py

| 상수 | 기본값 | 설명 |
|---|---|---|
| `SPACING_SAFETY_RATIO` | `0.15` | 단어 간격 수정 안전 비율. 15% 초과 변경 시 원본 유지 |

### chunker_step4.py

| 상수 | 기본값 | 설명 |
|---|---|---|
| `CHUNK_SIZE` | `500` | 최대 청크 크기 (문자 수) |
| `CHUNK_OVERLAP` | `100` | 청크 간 겹침 크기 (문자 수) |

### storage_step5.py

| 상수 | 기본값 | 설명 |
|---|---|---|
| `CHROMA_PATH` | `"DB/chroma_db"` | ChromaDB 영구 저장 경로 |
| `CHUNK_DIR` | `"output/chunks"` | 청크 JSON 디렉터리 |
| `EMBEDDING_MODEL` | `'jhgan/ko-sroberta-multitask'` | Dense 임베딩 모델 (768차원, 한국어 최적화) |
| BM25 `k` | `1.2` | Term frequency 포화 파라미터 |
| BM25 `b` | `0.75` | 문서 길이 정규화 파라미터 |
| BM25 `avg_doc_length` | `256.0` | 평균 문서 길이 (문자 수) |
| BM25 `token_max_length` | `40` | 최대 토큰 길이 |

---

## 7. CLI 사용 예시

모든 명령은 `preprocessor_v3.1/` 디렉터리에서 실행한다.

### 전체 파이프라인 실행

```bash
# data/ 디렉터리의 모든 HWP/PDF 파일을 처리
conda run -n langc python3 preprocessor.py
```

실행 결과:
- `output/temp_pdf/*.pdf` — 변환/복사된 PDF
- `output/step1_parsed_*.md` — 파싱된 마크다운
- `output/step2_audited_*.md` — 감사된 마크다운
- `output/chunks/chunk_*.json` — 청크 JSON
- `output/execution_summary.csv` — 실행 요약
- `DB/chroma_db/` — ChromaDB 데이터베이스

### 개별 단계 실행

```bash
# Step 1: PDF → 마크다운 (pdf_loader 직접 사용)
# preprocessor.py의 _documents_to_parsed_markdown()을 통해 실행됨
# 개별 실행은 아래 프로그래밍 방식 예시 참조

# Step 2: 감사기
conda run -n langc python3 auditor_step2.py
# output/step1_parsed_*.md → output/step2_audited_*.md

# Step 3-7: 청커
conda run -n langc python3 chunker_step4.py
# output/step2_audited_*.md (없으면 step1_parsed_*.md) → output/chunks/

# Step 4: 저장소 (청크 JSON이 이미 있을 때)
# storage_step5.py는 독립 CLI가 없음 — preprocessor.py 또는 프로그래밍 방식으로 사용
```

### HWP 파일 단독 변환

```bash
# 프로젝트 루트에서 실행
conda run -n langc python3 hwp_converter.py data/문서.hwp -o output/temp_pdf/
```

### 단일 파일 테스트

```bash
# 단일 PDF 파일 전체 파이프라인 테스트
conda run -n langc python3 -c "
from pathlib import Path
from preprocessor import process_single_pdf

result = process_single_pdf(
    Path('output/temp_pdf/기관명_사업명.pdf'),
    Path('output')
)
print(result)
"
```

```bash
# pdf_loader 단독 테스트
conda run -n langc python3 -c "
from pdf_loader import load_pdf
docs = load_pdf('output/temp_pdf/sample.pdf')
print(f'페이지 수: {len(docs)}')
for doc in docs[:2]:
    print(f'--- 페이지 {doc.metadata[\"page\"]} ---')
    print(doc.page_content[:200])
"
```

```bash
# 감사기 단독 테스트
conda run -n langc python3 -c "
from auditor_step2 import audit_file
audit_file('output/step1_parsed_sample.md', 'output/step2_audited_sample.md')
"
```

```bash
# 청커 단독 테스트
conda run -n langc python3 -c "
from pathlib import Path
from chunker_step4 import process_file, print_statistics

chunks = process_file(Path('output/step2_audited_sample.md'))
print_statistics(chunks)
"
```

---

## 8. 프로그래밍 방식 사용 예시

### 단일 PDF 전체 파이프라인

```python
from pathlib import Path
from preprocessor import process_single_pdf

pdf_path = Path('output/temp_pdf/기관명_사업명.pdf')
output_dir = Path('output')

result = process_single_pdf(pdf_path, output_dir)

if result['status'] == 'success':
    print(f"청크 수: {result['chunk_count']}")
    print(f"처리 시간: {result['duration_sec']:.1f}초")
else:
    print(f"실패: {result['error']}")
```

### HWP 변환 후 파이프라인 실행

```python
import sys
sys.path.insert(0, '..')  # 프로젝트 루트 (hwp_converter.py 위치)

from pathlib import Path
from hwp_converter import HWPConverter
from preprocessor import process_single_pdf

converter = HWPConverter()
result = converter.convert('data/문서.hwp', 'output/temp_pdf')

if result['success']:
    pdf_path = Path(result['output_file'])
    pipeline_result = process_single_pdf(pdf_path, Path('output'))
    print(pipeline_result)
```

### pdf_loader 단독 사용

```python
from pdf_loader import load_pdf

docs = load_pdf('output/temp_pdf/sample.pdf')

for doc in docs:
    print(f"페이지 {doc.metadata['page']}: {len(doc.page_content)}자")
    print(doc.page_content[:100])
    print()
```

### 감사기 단독 사용

```python
from auditor_step2 import (
    audit_file,
    detect_toc_pages,
    _extract_toc_heading_types,
)

# 전체 감사
audit_file('output/step1_parsed_sample.md', 'output/step2_audited_sample.md')

# TOC 감지만 수행
with open('output/step1_parsed_sample.md', encoding='utf-8') as f:
    text = f.read()

toc_pages = detect_toc_pages(text)
print(f"TOC 페이지: {sorted(toc_pages)}")

type_level = _extract_toc_heading_types(text, toc_pages)
print(f"헤딩 타입 매핑: {type_level}")
```

### 청커 단독 사용

```python
from pathlib import Path
from chunker_step4 import process_file, process_all_files, print_statistics

# 단일 파일
chunks = process_file(Path('output/step2_audited_sample.md'))
print_statistics(chunks)

# 여러 파일
files = sorted(Path('output').glob('step2_audited_*.md'))
output_dir = Path('output/chunks')
output_dir.mkdir(exist_ok=True)

all_chunks = process_all_files(files, output_dir)
print_statistics(all_chunks)
```

### 저장소 단독 사용 (청크 JSON이 이미 있을 때)

```python
import json
from pathlib import Path
from storage_step5 import (
    compute_doc_id,
    assign_uids,
    build_hierarchy,
    apply_section_uids,
    upsert_hybrid_chunks,
    upsert_hierarchy_chroma,
    verify_integrity,
)

# 청크 JSON 로드
chunk_dir = Path('output/chunks')
chunks = []
for f in sorted(chunk_dir.glob('chunk_*.json')):
    with open(f, encoding='utf-8') as fp:
        chunks.append(json.load(fp))

# doc_id 할당 (preprocessor.py가 이미 처리했다면 생략)
parsed_path = Path('output/step1_parsed_sample.md')
for chunk in chunks:
    chunk['doc_id'] = compute_doc_id(parsed_path)

# UID 및 계층 처리
assign_uids(chunks)
hierarchy_entries, section_uid_map = build_hierarchy(chunks)
apply_section_uids(chunks, section_uid_map)

# ChromaDB 저장
hybrid_count = upsert_hybrid_chunks(chunks)
hierarchy_count = upsert_hierarchy_chroma(hierarchy_entries)

print(f"청크 저장: {hybrid_count}개")
print(f"계층 저장: {hierarchy_count}개")

# 무결성 검증
verify_integrity(hybrid_count)
```

### 테이블 평탄화 단독 사용

```python
from table_flattener import flatten_table, flatten_tables_in_text

# 단일 테이블
table = """| 사업명 | 차세대 포털 |
|---|---|
| 사업기간 | 24개월 |
| 예산 | 5억 원 |"""

print(flatten_table(table))
# 출력:
# 사업명: 차세대 포털
# 사업기간: 24개월
# 예산: 5억 원

# 텍스트 내 모든 테이블 평탄화
with open('output/step1_parsed_sample.md', encoding='utf-8') as f:
    text = f.read()

flattened = flatten_tables_in_text(text)
```

### 텍스트 클리닝 단독 사용

```python
from text_cleaner import clean_text, clean_documents
from langchain_core.documents import Document

# 단일 텍스트
cleaned = clean_text("○ 사업 개요\n**중요 내용**\n- 3 -", file_type="pdf")

# Document 리스트
docs = [
    Document(page_content="○ 항목 1", metadata={"file_type": "pdf"}),
    Document(page_content="● 항목 2", metadata={"file_type": "hwp"}),
]
cleaned_docs = clean_documents(docs)
```
