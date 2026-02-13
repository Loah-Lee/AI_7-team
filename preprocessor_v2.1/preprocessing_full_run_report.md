# 전처리 파이프라인 전체 실행 보고서

**파이프라인 버전**: v2.1.3 (Strict Contract Enforcement)
**실행 일시**: 2025-02-13
**실행 환경**: conda `langc` (Python 3.10), NVIDIA RTX 4060 (8GB)

---

## 1. 실행 결과 요약

| 항목 | 값 |
|------|-----|
| 입력 파일 | 99개 PDF (`output/temp_pdf/`) |
| 성공 | **99/99** (실패 0) |
| 총 Chunk 수 | **8,185** |
| Dense (벡터) 행 수 | **8,185** |
| Sparse (FTS5) 행 수 | **8,185** |
| Dense == Sparse 불일치 | **0건** |
| 고유 doc_id 수 | **99** (파일 1:1 대응) |
| `unknown` doc_id | **0건** |
| DB 크기 | **114 MB** |
| 총 소요 시간 | **2,553초** (~42분) |

### Chunk 통계

| 항목 | 값 |
|------|-----|
| 평균 | 82.7개/파일 |
| 중앙값 | 76개/파일 |
| 최소 | 42개 |
| 최대 | 173개 |

### 시간 통계

| 항목 | 값 |
|------|-----|
| 평균 | 25.8초/파일 |
| 최소 | 12.5초 |
| 최대 | 54.8초 |

---

## 2. 무결성 검증 결과

| 검증 항목 | 결과 |
|-----------|------|
| 모든 chunk에 `doc_id` 존재 | PASS |
| 모든 chunk의 `metadata.doc_id` 존재 | PASS |
| `doc_id == "unknown"` 부재 | PASS |
| `chunk_count == sparse_count == dense_count` (99개 파일 전체) | PASS |
| `metadata.uid` 존재 | PASS |

---

## 3. 산출물 위치

| 산출물 | 경로 |
|--------|------|
| 최종 DB | `DB/document.db` |
| 파서 출력 (Markdown) | `output/step1_parsed_*.md` (99개) |
| 감사 출력 (정제 Markdown) | `output/step2_audited_*.md` (99개) |
| Chunk JSON | `output/chunks/chunk_*.json` |
| 실행 요약 CSV | `output/execution_summary.csv` |
| 파이프라인 코드 | `preprocessor_v2.1/*.py` (5개) |

---

## 4. `preprocessor.py`로 동일 결과 재현하는 방법

### 사전 조건

1. conda 환경 `langc` 활성화 상태
2. `data/` 폴더에 원본 HWP/PDF 파일 99개 존재
3. `output/temp_pdf/` 폴더에 변환된 PDF 99개 존재 (HWP→PDF 변환이 이미 완료된 경우)
4. GPU 사용 가능 (임베딩 모델 로드용)

### 재현 절차

#### 방법 A: 기존 DB를 지우고 처음부터 재생성

```bash
# 1. 기존 DB 삭제
rm -f DB/document.db

# 2. 기존 중간 산출물 삭제 (선택)
rm -f output/step1_parsed_*.md
rm -f output/step2_audited_*.md
rm -rf output/chunks/

# 3. preprocessor_v2.1 디렉토리를 모듈 경로에 추가하여 실행
conda run -n langc python3 -c "
import sys
sys.path.insert(0, 'preprocessor_v2.1')
import os
os.chdir('.')
exec(open('preprocessor_v2.1/preprocessor.py').read())
"
```

#### 방법 B: preprocessor_v2.1 파일들을 프로젝트 루트에 복사 후 실행

```bash
# 1. v2.1 파일을 루트로 복사 (기존 v2.0 파일 덮어쓰기)
cp preprocessor_v2.1/parser_step1.py .
cp preprocessor_v2.1/auditor_step2.py .
cp preprocessor_v2.1/chunker_step4.py .
cp preprocessor_v2.1/storage_step5.py .
cp preprocessor_v2.1/preprocessor.py .

# 2. 기존 DB 삭제
rm -f DB/document.db

# 3. 실행
conda run -n langc python3 preprocessor.py
```

#### 방법 C: 특정 파일만 재처리 (Upsert)

DB를 삭제하지 않고 특정 문서만 재처리하는 경우, doc_id 기반 Upsert가 작동하여
해당 문서의 기존 벡터가 삭제된 후 새로 삽입됩니다.

```bash
# 예: sample1.pdf만 재처리
conda run -n langc python3 -c "
import sys
sys.path.insert(0, 'preprocessor_v2.1')
from pathlib import Path
from preprocessor import process_single_pdf
result = process_single_pdf(Path('output/temp_pdf/sample1.pdf'), Path('output'))
print(result)
"
```

### 동일 결과 보장 조건

| 조건 | 설명 |
|------|------|
| 동일 PDF 입력 | `output/temp_pdf/`의 PDF가 동일해야 함 |
| 동일 코드 버전 | `preprocessor_v2.1/` 내 5개 `.py` 파일이 v2.1.3과 동일 |
| DB 초기 상태 | 처음부터 재생성 시 `DB/document.db` 삭제 필요 |
| 임베딩 모델 | `jhgan/ko-sroberta-multitask` (자동 다운로드됨) |

**참고**: `doc_id`는 parser 출력(step1_parsed_*.md)의 SHA-256 해시이므로,
동일 PDF → 동일 parser 출력 → 동일 doc_id → 동일 DB 상태가 보장됩니다.

### 결과 확인 방법

```bash
# execution_summary.csv 확인
cat output/execution_summary.csv | head -5

# DB 행 수 확인
conda run -n langc python3 -c "
import sqlite3
conn = sqlite3.connect('DB/document.db')
c = conn.cursor()
for table in ['chunks', 'sparse']:
    c.execute(f'SELECT COUNT(*) FROM {table}')
    print(f'{table}: {c.fetchone()[0]} rows')
c.execute('SELECT COUNT(DISTINCT doc_id) FROM sparse')
print(f'distinct docs: {c.fetchone()[0]}')
conn.close()
"
```

기대 결과:
- `chunks: 8185 rows`
- `sparse: 8185 rows`
- `distinct docs: 99`

---

## 5. 파이프라인 아키텍처 (v2.1.3)

```
PDF (99개)
  │
  ▼
parser_step1.py ─── 적응형 폰트 프로파일링, [[PAGE:N]] 마커 삽입
  │                  출력: step1_parsed_*.md
  ▼
auditor_step2.py ── 한국어 spacing 교정, 불릿 표준화, [[PAGE:N]] 보존
  │                  출력: step2_audited_*.md
  ▼
chunker_step4.py ── 섹션 기반 분할, kiwipiepy 문장 분리, 테이블 원자성
  │                  [[PAGE:N]] 소비 → chunk별 page range 정밀 추적
  │                  출력: chunk JSON
  ▼
storage_step5.py ── doc_id(SHA-256) 기반 Upsert
  │                  Dense: ko-sroberta 768d 벡터 (SQLiteVec)
  │                  Sparse: kiwipiepy 명사 추출 FTS5
  │                  Hierarchy: 섹션 경로 벡터
  ▼
DB/document.db ──── chunks(dense) + sparse(FTS5) + hierarchy
```

### 핵심 계약 (v2.1.2~v2.1.3)

- `assign_uids()`: Fail-Fast — doc_id 누락/무효/"unknown" 시 RuntimeError
- `initialize_sparse_db()`: Strict 직접 접근 — fallback 없음
- `upsert_dense_vectors()`: doc_id 기반 DELETE→INSERT — Append/Drop 금지
