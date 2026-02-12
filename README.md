# AI_7-team: RFP-RAG-Analyzer
> **100여 개의 RFP(제안요청서) 분석 및 요약을 위한 RAG 시스템 구축 프로젝트**

본 프로젝트는 복잡한 입찰 공고문(RFP)을 효율적으로 분석하여 컨설턴트의 의사결정을 돕는 AI 도구를 개발합니다.

---

## 프로젝트 구조

```
/Users/apple/AI_7-team
├─ src/                코드
├─ configs/            평가/쿼리 설정
├─ data/
│  └─ pdf_raw/         본작업 입력 원본(PDF/HWP→PDF, 로컬)
├─ data_index/
│  └─ dense_B/         B 파이프라인 Dense 인덱스(로컬)
├─ notebooks/          rich 파이프라인 산출물(로컬)
├─ artifacts/          실험 산출물(로컬)
├─ results/            실험 결과(로컬)
├─ README.md
└─ CODEX_CONSTITUTION.md
```

주의:
- `data/`, `data_index/`, `notebooks/`, `artifacts/`, `results/`는 **로컬 전용, 커밋 금지**
- `notebooks/`는 저장소에는 `.gitkeep`만 유지

---

## 기본 파이프라인

1. rich 추출(B)  
`data/pdf_raw/` → `notebooks/data_rich/`, `notebooks/data_assets/`

2. rich 청킹(B)  
`notebooks/data_rich/` → `notebooks/data_chunks_rich/`

3. Dense 인덱스 생성(B)  
`notebooks/data_chunks_rich/` → `data_index/dense_B/`

4. 평가(B)  
Hybrid(B) + rerank none 기준으로 평가  
입력 쿼리: `configs/eval_queries_v2_rich.jsonl`

참고:
- A 파이프라인(`data_text/`, `data_chunks/`, `data_index/dense_A`)은 현재 중단(legacy)

---

## 실행 예시

```
# rich 추출(B): 입력 data/pdf_raw, 출력 notebooks/data_rich + notebooks/data_assets
python -c "from pathlib import Path; from src.rich_pdf_extract import extract_rich; print(extract_rich(input_dir=Path('data/pdf_raw'), output_root=Path('notebooks/data_rich'), assets_root=Path('notebooks/data_assets')))"

# rich 청킹(B): 입력 notebooks/data_rich, 출력 notebooks/data_chunks_rich
python -c "from pathlib import Path; from src.rich_chunk import chunk_rich; chunk_rich(input_dir=Path('notebooks/data_rich'), output_dir=Path('notebooks/data_chunks_rich'))"

# Dense 인덱스(B): 출력 data_index/dense_B
python -m src.build_dense_index --variant B

# 캡션(선택): 미완료 항목만 재개, 결과는 notebooks/data_rich/*.md 반영
python -m src.rich_caption_assets --only-failed --workers 12

# 평가(B) (Hybrid + none): 결과는 notebooks/runs/<timestamp>/results.csv
python -c "from pathlib import Path; from src.eval_harness import run_eval; run_eval(input_path=Path('configs/eval_queries_v2_rich.jsonl'), retriever='hybrid', variant='B', rerank_mode='none', hybrid_alpha=0.8, k=10, table_multiplier=1.0)"
```

---

## 평가 기준

- 정성 점수(qual_score_top1_avg)는 0~2 범위의 평균
  - 0: 관련 없음
  - 1: 부분 일치/근거 불충분
  - 2: 키워드+값+섹션 일치
- 현재 기준 설정: **Hybrid(B) + none**
  - `hybrid_alpha=0.8`, `k=10`, `table_multiplier=1.0`
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

- `data/`, `data_index/`, `notebooks/`, `artifacts/`, `results/`는 **로컬 전용** (커밋 금지)
- `.env`는 **커밋 금지**
- 평가 재실행 시 `notebooks/runs/`에 새 결과가 생성됨
- 본작업 기준 경로: `data/pdf_raw` → `notebooks/data_rich`/`notebooks/data_chunks_rich` → `data_index/dense_B`

---

## 트러블슈팅

- OpenAI 호출 실패 시
  - DNS 문제 가능 → `networksetup -getdnsservers "Wi-Fi"` 확인
  - 필요 시 DNS 수동 설정: `1.1.1.1`, `1.0.0.1`
- Dense 인덱스 오류:
  - `data_index/dense_B` 재생성
