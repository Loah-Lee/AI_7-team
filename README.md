# AI_7-team: RFP-RAG-Analyzer
> **100여 개의 RFP(제안요청서) 분석 및 요약을 위한 RAG 시스템 구축 프로젝트**

본 프로젝트는 복잡한 입찰 공고문(RFP)을 효율적으로 분석하여 컨설턴트의 의사결정을 돕는 AI 도구를 개발합니다.

---

## 프로젝트 구조

```
/Users/apple/AI_7-team
├─ src/                코드
├─ configs/            평가/쿼리 설정
├─ data_raw/           MVP 입력(샘플용)
├─ data_text/          텍스트 추출 결과(로컬)
├─ data_chunks/        일반 청크 결과(로컬)
├─ data_index/         Dense 인덱스(로컬)
├─ notebooks/          rich 파이프라인 산출물(로컬)
├─ artifacts/          실험 산출물(로컬)
├─ results/            실험 결과(로컬)
├─ README.md
└─ CODEX_CONSTITUTION.md
```

주의:
- `data/`는 전체 원본 보관용(로컬 전용, 커밋 금지)
- `data_raw/`, `data_text/`, `data_chunks/`, `data_index/`, `notebooks/`, `artifacts/`, `results/`는 **로컬 전용, 커밋 금지**

---

## 기본 파이프라인

1. 원본 텍스트 추출  
`data/raw` → `data_text/`

2. 일반 청킹(A)  
`data_text/` → `data_chunks/`

3. rich 추출/청킹(B)  
`data/raw` → `notebooks/data_rich/` → `notebooks/data_chunks_rich/`

4. Dense 인덱스 생성  
`data_chunks/` → `data_index/dense_A`  
`notebooks/data_chunks_rich/` → `data_index/dense_B`

5. 평가  
Hybrid(B) + rule rerank 기준으로 평가  
입력 쿼리: `configs/eval_queries_v2_rich.jsonl`

---

## 실행 예시

```
# 텍스트 추출
python -c "from pathlib import Path; from src.ingest import ingest_all; print(ingest_all(input_dir=Path('data/raw'), output_dir=Path('data_text')))"

# 일반 청킹
python -c "from src.chunk_text import chunk_all; chunk_all()"

# rich 추출 + 청킹
python -c "from src.rich_pdf_extract import extract_rich; print(extract_rich(input_dir=__import__('pathlib').Path('data/raw')))"
python -c "from src.rich_chunk import chunk_rich; chunk_rich()"

# Dense 인덱스
python -m src.build_dense_index --variant A
python -m src.build_dense_index --variant B

# 평가 (Hybrid B + rule)
python -c "from pathlib import Path; from src.eval_harness import run_eval; run_eval(input_path=Path('configs/eval_queries_v2_rich.jsonl'), retriever='hybrid', variant='B', rerank_mode='rule', hybrid_alpha=0.5, k=10, table_multiplier=1.0)"
```

---

## 평가 기준

- 정성 점수(qual_score_top1_avg)는 0~2 범위의 평균
  - 0: 관련 없음
  - 1: 부분 일치/근거 불충분
  - 2: 키워드+값+섹션 일치
- 현재 기준 설정: **Hybrid(B) + rule**
  - `hybrid_alpha=0.5`, `k=10`, `table_multiplier=1.0`
- 평가 입력 파일: `configs/eval_queries_v2_rich.jsonl` (B 기준 gold)

---

## Streamlit 대시보드

- 파일: `streamlit_app.py`
- 기능:
  - 평가 요약
  - 쿼리별 Top1 텍스트
  - Gold 기반 Top2 텍스트
  - 원본 경로 + 표 샘플 + 이미지 썸네일
  - 쿼리/골드 매칭 테이블
- 실행:

```
pip install -r /Users/apple/AI_7-team/requirements.txt
streamlit run /Users/apple/AI_7-team/streamlit_app.py
```

---

## 운영 규칙

- `data/`, `data_raw/`, `data_text/`, `data_chunks/`, `data_index/`,
  `notebooks/`, `artifacts/`, `results/`는 **로컬 전용** (커밋 금지)
- `.env`는 **커밋 금지**
- 데이터 변경/평가 재실행 시 `notebooks/runs/`에 새 결과가 생성됨

---

## 트러블슈팅

- OpenAI 호출 실패 시
  - DNS 문제 가능 → `networksetup -getdnsservers "Wi-Fi"` 확인
  - 필요 시 DNS 수동 설정: `1.1.1.1`, `1.0.0.1`
- Dense 인덱스 오류:
  - `data_index/dense_A` 또는 `data_index/dense_B` 재생성
