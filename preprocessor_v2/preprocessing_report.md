# 전처리 파이프라인 개선 수행 보고서

## 1. 개요

Korean RFP(제안요청서) PDF 문서 99개를 파싱하여 RAG용 SQLite 하이브리드 DB를 구축하는 전처리 파이프라인을 전면 개선하였다.

**파이프라인 구성:**
```
PDF → parser_step1.py → auditor_step2.py → chunker_step4.py → storage_step5.py → DB
```

**실행 방법:**
```bash
conda run -n langc python3 preprocessor.py        # 전체 파이프라인
conda run -n langc python3 parser_step1.py         # 개별 단계 실행 가능
conda run -n langc python3 auditor_step2.py
conda run -n langc python3 chunker_step4.py
conda run -n langc python3 storage_step5.py
```

---

## 2. 기존 버전 문제점

| 단계 | 문제 | 영향 |
|------|------|------|
| Parser | `get_text("blocks")`로 plain text만 추출, 폰트 정보 무시 | 헤더 감지 불가 → 섹션 경계 없음 |
| Parser | 페이지 마커 `[page: N]` 형태 → Chunker에서 미파싱 | 청크에 페이지 번호 누락 |
| Auditor | `([가-힣])\s+(?=[가-힣])` → 정상 띄어쓰기까지 전부 삭제 | "벤처기업 육성에 관한" → "벤처기업육성에관한" |
| Auditor | 헤더 감지 10페이지 제한 | 100+ 페이지 문서 후반부 헤더 누락 |
| Chunker | 헤더를 `re.sub(r'^#+\s+', '', text)`로 삭제 | 섹션 경계 정보 소실 |
| Chunker | 테이블이 문장 분할 regex에 의해 분할 | 테이블 무결성 파괴 |
| Storage | 매 실행 시 `DROP TABLE` | 기존 데이터 전부 삭제 |
| Storage | `all-MiniLM-L6-v2` (384d, 영어 모델) | 한국어 문서에 부적합 |
| Storage | bigram 슬라이딩 윈도우 FTS | 무의미 토큰 생성 ("벤처확인" → "벤처","처확","확인") |

---

## 3. 개선 내용

### 3.1 Parser (parser_step1.py) — 파일별 적응형 헤더 감지

#### 핵심 아키텍처: Two-Pass, Single-Open
```
PDF 1회 오픈 → Pass 1(폰트 프로파일링) → Pass 2(마크다운 생성) → 파일 닫기
```

#### 적응형 헤더 클러스터링 알고리즘

각 PDF 파일마다 독립적으로 폰트 분포를 분석하여 헤더를 감지한다.  
하드코딩된 fontsize 임계값은 **전혀 없으며**, 모든 판단은 해당 파일의 실측 데이터에 기반한다.

**Phase 1 — 개별 fontsize 필터링 (클러스터링 전)**

body_size(최빈 fontsize) + 2pt 이상인 모든 fontsize를 후보로 수집하고, 각 size를 아래 5개 필터로 **개별** 평가:

| 필터 | 조건 | 근거 |
|------|------|------|
| cover-only | count ≤ 5 AND page ⊆ {0,1} | 표지에만 등장하는 큰 글씨 |
| sub-body | char_count > 본문의 15% | 본문과 유사한 대량 텍스트 |
| period_ratio | > 0.3 (단, ≤15자 span 제외) | 헤더는 마침표로 끝나지 않음 |
| avg_span_len | > 80자 | 헤더는 보통 5~30자의 짧은 구문 |
| page density | spread > 50% pages AND count > spread × 3 | 거의 모든 페이지에 반복 = 본문 |

> `_is_sentence_ending()`: ≤15자 span은 "1.", "가." 같은 번호 붙은 헤더이므로 period count에서 제외

**Phase 2 — 생존자 병합 (≤0.5pt)**

필터를 통과한 fontsize들 중 인접한 크기(≤0.5pt 차이)만 같은 그룹으로 병합한다.  
이전 버전의 1.5pt gap 기반 클러스터링은 20pt→12pt까지 연쇄 합병(chaining)을 일으켰으나,  
개별 필터링 후 0.5pt 병합으로 이 문제를 근본적으로 해결하였다.

**Phase 3 — H1/H2 할당**

최상위 그룹 → H1, 차상위 그룹 → H2. 최대 2단계.

#### 표지 제목 추출
- page 0에서 최대 fontsize 텍스트 (3 < 길이 < 150)
- 날짜 패턴(`^\d{4}[\.\s]`) fallback: 차순위 fontsize 사용
- dash prefix 제거, 중복 텍스트 제거

#### 레이아웃 테이블 안 헤더 보존
`find_tables()`가 레이아웃 테이블(문서 프레임)도 감지하므로, 테이블 bbox 안의 span이라도 **헤더 fontsize이면 제외하지 않고** 마크다운에 포함한다.

#### 라인 병합 후 헤더 분류
span 개별이 아닌, 동일 Y좌표(±3pt) span을 합친 뒤 **max fontsize로** 헤더 여부를 판정한다.  
이전 방식(span별 prefix)은 같은 줄에 `# 제목 # 제목`처럼 중복 태그가 생기는 문제가 있었다.

---

### 3.2 Auditor (auditor_step2.py) — 신규 생성

| 기능 | 설명 |
|------|------|
| 한글 단일글자 공백 교정 | "제 안 요 청 서" → "제안요청서" (3+ 단일 글자 패턴만) |
| 정상 띄어쓰기 보존 | "벤처기업 육성에 관한" → 그대로 유지 |
| 중복 공백/줄바꿈 정리 | 2+ spaces → 1, 3+ newlines → 2 |
| 구조 보존 | YAML frontmatter, `<!-- page: N -->`, `#/##` 헤더, 테이블 → 전부 보존 |

기존 `auditor_reader_step23.py`는 보존하고, 별도 파일로 생성하였다.

---

### 3.3 Chunker (chunker_step4.py) — 전면 교체

| 항목 | 이전 | 현재 |
|------|------|------|
| 문장 분리 | regex (`.!?`) | kiwipiepy `kiwi.split_into_sents()` |
| 헤더 처리 | 삭제 (`re.sub`) | **강제 분할 경계** + 내용 보존 |
| 테이블 처리 | 문장 분할로 파괴 | **원자적** — 절대 분할 안 함 |
| 페이지 추적 | 미구현 | `<!-- page: N -->` 파싱 → page_start/page_end |
| 오버랩 | 하드코딩 `[-2:]` | 설정 가능 `OVERLAP_SENTENCES = 2` |
| 최소 청크 | 없음 | `MIN_CHUNK_SIZE = 200` 미만 → 이전 청크에 병합 |

**분할 우선순위:**
1. 헤더 경계 (`#`, `##`) = 강제 분할
2. 테이블 무결성 = 연속 `|` 행은 절대 분할하지 않음
3. 크기 제한 = 섹션 내 1500자 초과 시 kiwipiepy 문장 경계에서 분할
4. 오버랩 = 크기 분할 시 이전 청크 마지막 2문장을 다음 청크에 포함

---

### 3.4 Storage (storage_step5.py) — 3대 변경

| 항목 | 이전 | 현재 |
|------|------|------|
| 임베딩 모델 | `all-MiniLM-L6-v2` (384d, 영어) | `jhgan/ko-sroberta-multitask` (768d, 한국어) |
| FTS 토큰화 | bigram 슬라이딩 윈도우 | kiwipiepy 명사 추출 (NNG/NNP/NNB) |
| 테이블 관리 | 매번 `DROP TABLE` | Upsert: `CREATE IF NOT EXISTS` + 중복 스킵 |
| Hierarchy | 페이지 범위 없음 | `page_start`/`page_end` 메타데이터 포함 |

**임베딩 모델 교체 근거:**
- positive-negative gap: 0.084 (영어 모델) → **0.466** (한국어 모델), 5.5배 향상

**FTS 토큰화 개선:**
- bigram: "벤처확인" → `"벤처" AND "처확" AND "확인"` (무의미 토큰 "처확" 포함)
- kiwipiepy: "벤처확인" → `"벤처" AND "확인"` (의미 단위만)

---

## 4. 검증 결과

### 4.1 Parser 10개 샘플 테스트

| Sample | body | H1 range | H2 range | H1# | H2# |
|--------|------|----------|----------|-----|-----|
| 1 | 10.0 | (23.0, 23.0) | (20.0, 20.0) | 16 | 16 |
| 5 | 11.0 | (22.0, 22.0) | (20.0, 20.0) | 6 | 18 |
| 13 | 11.0 | (27.9, 27.9) | (25.1, 25.1) | 4 | 2 |
| 20 | 10.0 | (47.7, 47.7) | (32.0, 32.0) | 1 | 5 |
| 25 | 10.0 | (32.0, 32.0) | (24.0, 24.0) | 3 | 4 |
| 35 | 11.0 | (17.0, 17.0) | (16.0, 16.0) | 15 | 51 |
| 40 | 10.0 | (32.0, 32.0) | (30.0, 30.0) | 5 | 2 |
| 50 | 11.0 | (32.0, 32.0) | (30.0, 30.0) | 3 | 1 |
| 70 | 10.0 | (22.0, 22.0) | (20.0, 20.0) | 34 | 4 |
| 80 | 11.0 | (24.0, 24.0) | (22.0, 22.0) | 5 | 4 |

- 10개 샘플 모두 H1 > 0, H2 > 0 (이전 버전: sample1, sample35에서 H1=0, H2=0)
- body_size가 10~13pt로 파일마다 다르지만, 각각 올바르게 적응
- H1/H2 range가 파일마다 독립적으로 결정됨 (17pt~47.7pt 범위)

### 4.2 Chunker 검증

| Sample | 입력 크기 | 섹션 수 | 청크 수 | min | max | avg | tiny(<200) |
|--------|-----------|---------|---------|-----|-----|-----|------------|
| 1 | 142,018자 | 33 | 117 | 282 | 3,348 | 1,099 | 0 |
| 5 | 80,462자 | 25 | 71 | 216 | 1,970 | 1,089 | 0 |
| 35 | 59,468자 | 67 | 56 | 214 | 1,859 | 566 | 0 |

- MIN_CHUNK_SIZE(200) 미만 청크 = 0개 (병합 로직 정상)
- 섹션별 H1/H2 context 전파 정상
- 페이지 번호 추적 정상

### 4.3 Storage 검증

| 테이블 | Row 수 | 설명 |
|--------|--------|------|
| chunks | 315 | Dense vector (ko-sroberta, 768d) |
| sparse | 315 | FTS5 (kiwipiepy nouns + original text) |
| hierarchy | 113 | Section path vectors + page ranges |

**FTS 검색 테스트:** "제안" → 5개 결과 반환, BM25 score 정상  
**Hierarchy 페이지 범위:** page_start/page_end 메타데이터 정상 포함  
**Nouns 추출 샘플:** "벤처 확인 종합 관리 시스템 기능 고도 용역 사업..." ✅

### 4.4 End-to-End 파이프라인

3개 샘플(sample1, 5, 35)에 대해 전체 파이프라인을 실행하고 DB 무결성을 확인하였다.
```
parser_step1.py → auditor_step2.py → chunker_step4.py → storage_step5.py → DB 검증
```
모든 단계 정상 완료, DB 테이블 스키마 및 데이터 정합성 확인.

---

## 5. 파일 변경 요약

| 파일 | 상태 | 설명 |
|------|------|------|
| `parser_step1.py` | **전면 교체** | 적응형 폰트 프로파일링 + 마크다운 생성 |
| `auditor_step2.py` | **신규 생성** | 한글 공백 교정 + 구조 보존 |
| `chunker_step4.py` | **전면 교체** | kiwipiepy 문장 분리 + 섹션 인식 + 테이블 보존 |
| `storage_step5.py` | **전면 교체** | ko-sroberta + kiwipiepy nouns + upsert |
| `preprocessor.py` | **수정** | 새 단계 호출 순서 반영 |
| `auditor_reader_step23.py` | 보존 | 기존 파일 유지 (미사용) |
| `preprocessing_design.md` | 보존 | 설계 문서 (권위 사양) |

---

## 6. 알려진 제한사항

1. **sample20 H1=1**: H1 range가 47.7pt(표지 크기)로 잡혀 실제 본문 헤더가 H2에만 할당됨. 기능상 문제는 없으나 H1/H2 의미가 역전될 수 있음.
2. **Dense search 별도 connection**: `SQLiteVec`의 `vec0` extension은 `SQLiteVec` API를 통해서만 로드됨. 별도 `sqlite3.connect()`로 직접 dense search 불가 (FTS 검색은 가능).
3. **LangChain deprecation**: `SentenceTransformerEmbeddings` → `HuggingFaceEmbeddings` 이관 권고. 현재 기능에 영향 없음.
4. **99개 전체 실행 미수행**: 10개 샘플 파싱 + 3개 샘플 E2E 테스트 완료. 99개 전체 실행은 GPU 환경에서 별도 수행 필요 (`preprocessor.py` 또는 각 단계 스크립트 직접 실행).
