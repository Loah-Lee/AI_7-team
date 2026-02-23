# src/parsers — 문서 파싱 + 청킹 + 클리닝

## 파이프라인 흐름

```
원본 문서 (PDF/HWP)
  → pdf_loader.py / hwp_loader.py   (Document 변환)
  → text_cleaner.py                  (노이즈 제거 + 테이블 평탄화)
  → chunker.py                       (청킹 + 메타데이터 부착)
  → VectorStore에 저장
```

## 파일 구성

| 파일 | 역할 | 핵심 함수 |
|------|------|----------|
| `pdf_loader.py` | PDF → Document | `load_pdf()` — pymupdf4llm 기반 마크다운 변환 |
| `hwp_loader.py` | HWP → Document | `load_hwp()` — Windows: pyhwpx, macOS/Linux: olefile+zlib |
| `chunker.py` | 청킹 + 메타데이터 | `chunk_documents()` |
| `text_cleaner.py` | 텍스트 정규화 | `clean_text()`, `clean_documents()` |
| `table_flattener.py` | 마크다운 테이블 → 자연어 | `flatten_table()`, `flatten_tables_in_text()` |

## 상세

### pdf_loader.py
- `pymupdf4llm.to_markdown(page_chunks=True)` — 페이지별 마크다운 생성
- 아티팩트 정리: 연속 빈 줄 축소, 독립 페이지 번호 제거
- 메타데이터: `source`(파일명, NFC 정규화), `file_type: "pdf"`, `page`(1-indexed)

### hwp_loader.py
- **Windows**: `pyhwpx.HWPExtractor` (COM 자동화)
- **macOS/Linux**: `olefile` + `zlib`로 HWP 5.x OLE2 바이너리 직접 파싱
  - `HWPTAG_PARA_TEXT`(tag_id=67) 레코드에서 UTF-16LE 텍스트 추출
  - 확장 제어 문자(1-23, 8바이트) 스킵 처리
- HWP는 페이지 구분 없음 → 단일 Document 반환

### text_cleaner.py
- 적용 순서:
  1. (PDF only) 마크다운 테이블 → 자연어 평탄화 (`table_flattener.py`)
  2. 불릿 기호 정규화 (○□❍ → `- `)
  3. Bold markdown 제거 (`**text**` → `text`)
  4. Heading markdown 제거 (`## text` → `text`)
  5. 수평선 제거 (HWP only)
  6. 반복 머리말/꼬리말 제거 (페이지 번호, 제안요청서 등)
  7. 공백 정규화

### table_flattener.py
- 마크다운 테이블을 임베딩 친화적 자연어로 변환
- 2열 key-value 테이블: `"사업명: 차세대 포털"` 형식
- 다열 테이블: `"header1: val1, header2: val2"` 형식
- 플레이스홀더 헤더(Col1/Col2): 헤더 없이 값만 출력
- 테이블 앞 제목 텍스트 보존

### chunker.py
- `RecursiveCharacterTextSplitter` (chunk_size=1000, overlap=200)
- **PDF 전용**: 테이블 블록 감지 → 행 경계에서 분할 (헤더 유지)
- 소형 텍스트 블록(<120자)은 인접 테이블에 병합
- 메타데이터 자동 부착:
  - `institution`, `project_name` — 파일명 `기관명_사업명.ext` 패턴에서 추출
  - `section` — 섹션 제목 패턴 매칭 (제N장, 1.1, 가. 등)
  - `is_toc` — 목차/표지 탐지 (점선 패턴, 키워드, 페이지 1 + 300자 미만)
  - `is_form` — 서식/양식 탐지 (서약서/동의서 키워드, 빈 필드 패턴)
  - `page` — HWP 등 페이지 없는 문서에 chunk 인덱스 부여
- 같은 source 내 중복 제거 (첫 200자 MD5 해시)
- 최소 길이 필터: 120자 미만 제거

## dev-yc 브랜치와의 차이

| 항목 | integration-eval-yc | dev-yc |
|------|---------------------|--------|
| PDF 파서 | `pymupdf4llm` (마크다운 변환) | `pdfplumber` (텍스트 + 테이블 분리) |
| 텍스트 클리닝 | `text_cleaner.py` (6단계 파이프라인) | 없음 (파서 내 최소 정리) |
| 테이블 처리 | `table_flattener.py` (자연어 변환) | CSV 템플릿 기반 마크다운 |
| 청킹 | 테이블 인식 분할 + 메타데이터 자동 추출 | `MarkdownChunker` (미사용) |
| TOC/서식 탐지 | chunker에서 `is_toc`, `is_form` 태깅 | metadata_filter에서 런타임 필터 |
| CSV 지원 | 없음 | `csv_loader.py` |
