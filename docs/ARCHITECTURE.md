# ARCHITECTURE

## 구조 개요
- App: `app/main.py` (기본), 보조: `app/streamlit_app.py`, `app/gold_app.py`
- Core: `src/graph`, `src/parsers`, `src/retrievers`, `src/evaluation`, `src/rag_answer.py`
- Scripts: `scripts/` (예: `scripts/rebuild_db.py`)
- Docs/Eval: `docs/`, `eval_resources/`
- Data/index outputs (로컬 전용): `notebooks/`, `results/`, `data_index/`

## Chroma 검색 아키텍처
- 핵심 클래스: `src/retrievers/vectorstore.py`의 `VectorStore`
- 임베딩 제공자:
  - `OpenAIEmbeddingProvider` (`text-embedding-3-small`)
- 검색 방식:
  - 텍스트/쿼리 임베딩 후 cosine 공간(`hnsw:space=cosine`) 검색
  - 결과는 `source`, `org`, `type`, `chunk_index`, `chunk_id` 메타데이터와 함께 반환
- 필터:
  - `org`, `type`, `source` metadata filter 지원
- 부가 기능:
  - `get_ranking()`으로 org 단위 hit 랭킹 계산 가능

## Hybrid 검색 아키텍처
- 점수 결합식: `score = alpha * lexical + (1-alpha) * dense`
- `alpha=1.0`이면 lexical-only(실질 dense 비활성)
- `alpha<1.0`이면 lexical+dense 결합(진짜 hybrid)
- 기관/메타 필터는 query org 힌트와 metadata를 함께 사용

## 엔트리포인트
- Streamlit
  - `streamlit run /Users/apple/AI_7-team/app/main.py`
  - `streamlit run /Users/apple/AI_7-team/app/streamlit_app.py`
  - `streamlit run /Users/apple/AI_7-team/app/gold_app.py`
- 평가
  - `python -m src.run_eval_b`
  - `python -m src.evaluate_answer --eval-set configs/answer_eval_v1.jsonl --pred results/node_report_rag_final.csv`
- RAG 응답
  - `python -m src.rag_answer --query \"...\" --retriever hybrid --rerank none --generate`
- 벡터 DB
  - `python /Users/apple/AI_7-team/scripts/rebuild_db.py --dense --chroma`

## 시나리오 B 운영 기본값
- Hybrid: `retriever=hybrid`, `rerank=none`, `top_k=50`, `context_k=20`, `hybrid_alpha=1.0`
- Chroma: `collection=rfp_b_oai`, `model=text-embedding-3-small`
- 필수 환경변수: `OPENAI_API_KEY`
- 비교 실험 권장: `hybrid_alpha=0.9` 또는 `retriever=chroma`를 함께 실행해 벡터 기여도 확인

## 래퍼/어댑터 정책
- 래퍼: 기존 실행 경로를 유지하기 위한 얇은 실행 파일
  - 예: `app/streamlit_app.py`는 기존 `streamlit_app.py`를 `runpy`로 실행
- 어댑터: 기존 로직을 새 구조로 재노출하는 모듈
  - 예: `src/parsers/pdf_loader.py`는 `src/parsers/ingest_pdf.py`를 감싼 함수

## 점진적 변경 원칙
1. 기존 실행 경로를 유지한다.
2. 새 구조로 래퍼/어댑터를 추가한다.
3. 실제 호출을 새 구조로 옮긴다.
4. 레거시 래퍼를 단계적으로 제거한다.
