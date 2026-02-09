# PDF 청크 품질 개선 작업 리포트

**작성일시**: 2026-02-09 22:30
**작업자**: Claude Code (Opus 4.6)
**브랜치**: feature/integration-eval-yc

---

## 1. User Prompt

DB 분석 결과 PDF vs HWP 청크 품질 격차가 심각하여 개선 요청:
- PDF 청크의 70.4%가 마크다운 테이블 → 임베딩 유사도 저하
- PDF 평균 길이 608자 (HWP 911자), 22.8%가 200자 미만
- 대형 테이블이 동일 헤더로 24개 중복 청크 생성
- 서식/양식(서약서, 동의서 등)이 12.8% 차지
- 근본 원인: text_cleaner가 테이블을 통과시키고 청커가 테이블을 행 단위로만 분할

4가지 변경사항 구현 계획:
1. 테이블 평탄화
2. 서식/양식 노이즈 태깅
3. 청크 중복 제거
4. 최소 청크 길이 상향

---

## 2. Thinking Process

### 테이블 평탄화 전략
- 마크다운 테이블(`|Col1|Col2|...`)을 자연어 형태로 변환하면 임베딩 유사도가 크게 향상됨
- 2열 KV 테이블 vs 다열 테이블을 구분하여 최적 포맷 적용
- KV 테이블에서 헤더 행 자체가 데이터인 경우(`|사업명|차세대 포털|`)와 일반 열 제목(`|항목|내용|`) 구분 필요
- `_GENERIC_KV_HEADERS` 집합으로 한국어 일반 헤더(항목, 내용, 구분, 설명 등) 감지

### 서식/양식 처리
- 서약서, 동의서 등은 RAG 검색에서 노이즈 → 검색 시 필터링
- 완전 제거가 아닌 `is_form` 메타데이터 태깅 방식 채택 (데이터 보존)

### 중복 제거 전략
- source 파일 단위로만 적용 (cross-document 중복은 의도적일 수 있음)
- 첫 200자 MD5 해시로 동일성 판별 (전체 텍스트 비교 대비 효율적)

### 최소 길이 상향
- 80자 → 120자: 한국어 2~3문장, RAG에서 의미 있는 최소 단위

---

## 3. Execution Result

### 수정 파일 목록

| 파일 | 변경 유형 | 설명 |
|---|---|---|
| `src/parsers/table_flattener.py` | **신규** | 마크다운 테이블 → 자연어 변환 모듈 |
| `src/parsers/text_cleaner.py` | 수정 | PDF 테이블 평탄화 통합, 테이블 보호 로직 제거 |
| `src/parsers/chunker.py` | 수정 | `_is_form_chunk`, `_deduplicate_chunks` 추가, `_MIN_CHUNK_LENGTH` 80→120 |
| `src/retrievers/metadata_filter.py` | 수정 | `is_form` 필터링 추가 (mmr + similarity) |
| `scripts/audit_db.py` | 수정 | PDF 전용 검증 지표 추가 |

### 주요 구현 내용

#### table_flattener.py
- `flatten_table()`: 단일 테이블 변환
  - 2열 KV: `사업명: 차세대 포털` 형식
  - 다열: `구분: 인건비, 금액: 10억` 형식
  - `Col1/Col2` 플레이스홀더 → 헤더 없이 값만
  - 한국어 일반 헤더 자동 감지 (`항목`, `내용`, `구분`, `설명` 등)
- `flatten_tables_in_text()`: 전체 텍스트에서 테이블 블록 자동 탐지/변환

#### chunker.py
- `_is_form_chunk()`: 상단 200자에 서식 키워드 또는 빈 필드 패턴 3회 이상
- `_deduplicate_chunks()`: source별 첫 200자 MD5 해시 중복 제거
- `_MIN_CHUNK_LENGTH`: 80 → 120

### 검증 결과 (단위 테스트)

```
# 테이블 평탄화
Before: |사업명|차세대 포털|\n|---|---|\n|사업기간|24개월|
After:  사업명: 차세대 포털\n사업기간: 24개월  ✅

# 서식 감지
"입찰참가 서약서\n\n상기 내용을..." → is_form: True  ✅
"사업 개요 본 사업은..." → is_form: False  ✅

# 중복 제거
5 chunks (3 duplicates in same source) → 3 chunks  ✅

# 모든 모듈 import 성공  ✅
# VS Code diagnostics: 0 errors  ✅
```

### 기대 효과 (재인제스트 후)

| 지표 | Before | After (예상) |
|---|---|---|
| PDF 테이블 청크 비율 | 70.4% | <15% |
| PDF 평균 길이 | 608자 | >800자 |
| PDF 200자 미만 | 22.8% | <5% |
| 동일 헤더 중복 | 24개 | 1~2개 |
| HWP 청크 | 변동 없음 | 동일 |

### 검증 방법

```bash
uv run python scripts/audit_db.py --label before   # Before 스냅샷
uv run python scripts/ingest.py --reset             # 재인제스트
uv run python scripts/audit_db.py --label after     # After 비교
```
