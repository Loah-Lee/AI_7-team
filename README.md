# AI_7-team: BiddingMate RAG (Chroma 기준)
> 본 문서는 **현재 코드 기준 최신 Chroma 운영 흐름**을 정리한 README입니다.  
> 목적: 데이터 구축부터 평가 리포트까지 각 파트의 핵심 로직, 설계 근거, 관련 파일 경로를 빠르게 확인.

## 1) 현재 운영 기본값 (요약)

- 서비스 챗봇 기본:
  - `retriever=chroma`, `rerank=none`, `top_k=50`, `context_k=20`
  - 근거: `app/main.py`, `src/graph/workflow.py`
- Chroma 운영 옵션:
  - `org_filter_mode=hard`, `noise_mode=hard`, `mmr=True`, `query_rewrite=True`
  - 근거: `src/graph/workflow.py`, `src/rag_answer.py`
- 평가 기본:
  - 데이터셋 `eval_resources/eval_dataset.yaml`
  - `top_k=5`, `context_k=20`
  - `answer_model=gpt-5-nano`, `judge_model=gpt-5-mini`
  - 근거: `scripts/eval_retrieval.py`

## 2) E2E 아키텍처 (데이터 구축 → 생성/평가)

| 파트 | 핵심 로직 | 근거(왜 이렇게 동작) | 핵심 파일 |
|---|---|---|---|
| 1. 문서 파싱/자산 추출 | PDF 텍스트 추출 + 이미지 asset 추출 + HWP 자동 PDF 변환(`soffice`) | 원문 구조/이미지 근거를 동시에 보존해야 후속 검색·답변 품질이 안정적 | `src/parsers/rich_pdf_extract.py` |
| 2. 이미지/표 캡션 보강(선택) | 이미지별 LLM 캡션/표 텍스트 추출 후 markdown의 `PLACEHOLDER` 대체 | 표/이미지 기반 질의의 검색 가능 토큰을 늘려 recall 개선 | `src/parsers/rich_caption_assets.py` |
| 3. 구조 기반 청킹 | 목차/섹션/리스트 경계를 우선 반영해 chunk 생성, metadata(`section_title`, `page_refs`, `assets`) 포함 | 단순 길이 분할보다 질의-근거 정합성이 좋아져 retrieval precision 개선 | `src/parsers/rich_chunk.py` |
| 4. Chroma 인덱싱 | OpenAI 임베딩(`text-embedding-3-small`)으로 JSONL 청크를 Chroma에 upsert, 임베딩 lock 파일로 모델 일치 강제 | 인덱싱/검색 임베딩 불일치 차원 오류를 예방하고 재현성 확보 | `src/retrievers/chroma_store.py`, `src/retrievers/vectorstore.py`, `src/retrievers/build_chroma_index.py` |
| 5. 리트리버(핵심) | 기관 힌트 추출→기관 필터 검색 우선→fallback, Chroma score + lexical score + keyword/signal bonus + noise penalty, 필요 시 sparse MMR | 범용 질의·기관 질의를 동시에 커버하면서 source recall과 정밀도의 균형을 맞춤 | `src/rag_answer.py` (`ChromaRetriever.retrieve`) |
| 6. 오케스트레이션 | query type 파싱(`money_rank`, `asset` 등), 기본/자산/금액순위 경로 분기, 후보/컨텍스트 neighbor 확장 후 답변 생성 | 질의 유형별 실패 패턴이 달라 단일 경로보다 분기 처리 시 정답률이 높음 | `src/graph/nodes.py`, `src/graph/workflow.py` |
| 7. 프롬프트/답변 생성 | 규칙 기반 factoid 추출 우선, 실패 시 JSON 강제 LLM 생성(`status/answer/citations`), placeholder 응답 제거 | 값 추출형 질의에서 불필요한 장문 생성/환각을 줄이고 citation 일관성 확보 | `src/rag_answer.py` (`_rule_based_answer`, `generate_answer`, `generate_money_rank_answer`) |
| 8. 앱 응답/UI | image-only 질의 시 답변 텍스트 내 이미지 경로를 실제 파일로 resolve 후 바로 렌더 | “설명 대신 이미지 바로 제시” 요구 대응 | `app/main.py` |
| 9. 평가/리포트 | eval dataset 일괄 실행→LLM Judge 4지표 채점→`eval_results_current.json`→HTML 리포트 생성 | 실험별 성능을 동일 입력셋으로 비교하고 추적 가능 | `scripts/eval_retrieval.py`, `src/evaluation/llm_judge.py`, `scripts/build_eval_report.py` |

## 3) 파트별 상세 파일 맵

- 파싱/청킹
  - `src/parsers/rich_pdf_extract.py`
  - `src/parsers/rich_caption_assets.py`
  - `src/parsers/rich_chunk.py`
- 인덱스 구축
  - `scripts/rebuild_db.py`
  - `src/retrievers/build_chroma_index.py`
  - `src/retrievers/chroma_store.py`
  - `src/retrievers/vectorstore.py`
- 검색/생성
  - `src/graph/workflow.py`
  - `src/graph/nodes.py`
  - `src/rag_answer.py`
- 평가/리포트
  - `scripts/eval_retrieval.py`
  - `src/evaluation/llm_judge.py`
  - `scripts/build_eval_report.py`
  - `eval_resources/eval_dataset.yaml`
- 실행 앱
  - `app/main.py`

## 4) 실행 순서 (Chroma 최신 기준)

### 4-1. 환경 준비

```bash
cd /Users/apple/AI_7-team
pip install -r requirements.txt
```

- 필수: `OPENAI_API_KEY`
- 선택:
  - `LLM_JUDGE_TIMEOUT_SEC` (기본 90초)
  - `RAG_EXP5_FACTOID_GUARD` (기본 true)
  - `RAG_EXP6_STRUCTURED_COMPLEX` (기본 false)

### 4-2. 데이터 구축

```bash
# 1) rich 추출 (PDF/HWP -> markdown + assets)
python -c "from pathlib import Path; from src.parsers.rich_pdf_extract import extract_rich; print(extract_rich(input_dir=Path('data/pdf_raw'), output_root=Path('notebooks/data_rich'), assets_root=Path('notebooks/data_assets')))"

# 2) (선택) 이미지/표 캡션
python -m src.parsers.rich_caption_assets --only-failed --workers 8

# 3) 구조 기반 청킹
python -c "from pathlib import Path; from src.parsers.rich_chunk import chunk_rich; chunk_rich(input_dir=Path('notebooks/data_rich'), output_dir=Path('notebooks/data_chunks_rich'), chunk_size=1000, overlap=100)"

# 4) Chroma 인덱스 생성 (운영 컬렉션명에 맞춤)
python scripts/rebuild_db.py --chroma --chunk-output-dir notebooks/data_chunks_rich --chroma-dir data_index/chroma_B --collection rfp_b_oai_clean_v1 --model text-embedding-3-small
```

참고:
- `scripts/rebuild_db.py`의 기본 collection은 `rfp_b_oai`지만,
  운영/평가 기본은 `rfp_b_oai_clean_v1`이므로 collection 명을 명시하는 것을 권장.

### 4-3. 서비스 실행

```bash
streamlit run /Users/apple/AI_7-team/app/main.py
```

### 4-4. 평가 + HTML 리포트 생성

```bash
# Chroma 평가 (동일 eval dataset)
python scripts/eval_retrieval.py \
  --dataset eval_resources/eval_dataset.yaml \
  --retriever chroma \
  --rerank none \
  --top_k 5 \
  --context_k 20 \
  --answer-model gpt-5-nano \
  --judge-model gpt-5-mini \
  --chroma-collection rfp_b_oai_clean_v1 \
  --label current

# eval_resources/eval_results_current.json -> eval_resources/eval_report.html
python scripts/build_eval_report.py
```

### 4-5. Lexical 비교 평가(동일 쿼리)

```bash
python scripts/eval_retrieval.py \
  --dataset eval_resources/eval_dataset.yaml \
  --retriever tfidf \
  --rerank none \
  --top_k 5 \
  --context_k 20 \
  --answer-model gpt-5-nano \
  --judge-model gpt-5-mini \
  --label lexical
```

- JSON 결과는 `results/main_eval_<timestamp>/` 및 `eval_resources/`에 저장.
- HTML 출력 파일(`eval_report.html`, `eval_lexical_report.html`)은 `eval_resources/`에서 확인.

## 5) 프롬프트/생성 설계 포인트

- 질문 유형 감지:
  - 금액/비율/기간/연락처/이미지/순위 질의를 분기 처리
  - 파일: `src/graph/nodes.py`, `src/rag_answer.py`
- 규칙 기반 우선:
  - factoid 질의는 regex + relevance guard로 빠르게 값 추출
  - 파일: `src/rag_answer.py` (`_rule_based_answer`)
- LLM 생성 형식 고정:
  - JSON 응답(`status`, `answer`, `citations`) 강제
  - placeholder 문구 제거 처리 포함
  - 파일: `src/rag_answer.py` (`generate_answer`)
- 참고:
  - `src/prompts/templates.py`의 템플릿은 현재 런타임 핵심 경로가 아님(실제 지시문은 `generate_answer`에서 동적으로 구성).

## 6) 운영 시 체크리스트

- 인덱스 모델/컬렉션 일치 확인
  - 인덱싱과 검색이 같은 collection/model 조합인지 확인
  - 파일: `src/retrievers/chroma_store.py`
- 평가 결과 파일 갱신 확인
  - `eval_resources/eval_results_current.json`이 최신인지 확인 후 HTML 생성
- need_org 응답 대응
  - 기관명 없는 짧은 질의는 `need_org`가 의도된 동작
  - 파일: `src/graph/workflow.py`

## 7) 저장소 운영 규칙

- 커밋 금지(로컬 전용): `data/`, `data_index/`, `notebooks/`, `results/`, `.env`, `tests/`
- 평가 산출물은 실험 비교용으로 남기되, 불필요한 대용량 중간 산출물은 정리 권장
