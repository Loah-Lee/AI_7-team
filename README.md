# BiddingMate (입찰메이트)

> **B2G 입찰 컨설팅을 위한 RFP 분석 RAG 시스템**

100여 개의 RFP(제안요청서)를 효율적으로 분석하여 입찰 컨설턴트의 의사결정을 지원하는 LangGraph 기반 AI 시스템입니다.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green.svg)](https://langchain-ai.github.io/langgraph/)
[![uv](https://img.shields.io/badge/uv-managed-orange.svg)](https://github.com/astral-sh/uv)

---

## 주요 기능

- **다중 문서 질의응답**: 100+ RFP 문서 대상 검색 및 요약
- **LangGraph 워크플로우**: 질의 분석 → 검색 → 근거 추출 → 생성 4단계 파이프라인
- **하이브리드 검색**: MMR + 메타데이터 필터링 (기관명, 프로젝트명, 연도)
- **LLM-as-Judge 평가**: Correctness, Answer Coverage, Faithfulness, Context Relevance 4지표
- **HWP/PDF 지원**: 한국 공공기관 표준 문서 형식 파싱

---

## 빠른 시작

### 1. 환경 설정

```bash
# Python 3.11+ 필요
uv sync

# .env 파일에 API 키 설정
cp .env.example .env
# OPENAI_API_KEY=sk-... 입력
```

### 2. 문서 인덱싱

`data/files/`에 PDF/HWP 파일을 넣은 뒤:

```bash
# 최초 인덱싱
uv run python scripts/ingest.py

# DB 초기화 후 재인덱싱
uv run python scripts/ingest.py --reset

# DB 품질 감사 (선택)
uv run python scripts/audit_db.py --label v1
```

### 3. Streamlit 앱 실행

```bash
streamlit run app/main.py
```

브라우저에서 http://localhost:8501 접속

### 4. RAG 평가 실행

```bash
# E2E 평가 (LLM-as-Judge)
uv run python scripts/eval_retrieval.py --label current --top_k 5

# HTML 리포트 생성
uv run python scripts/build_eval_report.py

# 결과 확인
open eval_resources/eval_report.html
```

---

## 프로젝트 구조

```
AI_7-team/
├── app/
│   └── main.py                    # Streamlit UI 진입점
│
├── src/
│   ├── graph/                     # LangGraph 워크플로우
│   │   ├── state.py               #   RFPState TypedDict 정의
│   │   ├── nodes.py               #   4개 노드: analyze_query, retrieve, extract_evidence, generate
│   │   └── workflow.py            #   StateGraph 조립 (build_graph)
│   │
│   ├── parsers/                   # 문서 파싱 및 전처리
│   │   ├── pdf_loader.py          #   PDF 파서 (pymupdf4llm)
│   │   ├── hwp_loader.py          #   HWP 파서 (pyhwpx, Windows-only)
│   │   ├── text_cleaner.py        #   텍스트 정규화 (불릿, 폼 태깅, 중복 제거)
│   │   └── chunker.py             #   RecursiveCharacterTextSplitter (1000/200)
│   │
│   ├── retrievers/                # 검색 시스템
│   │   ├── embeddings.py          #   OpenAI text-embedding-3-small
│   │   ├── vectorstore.py         #   Chroma persistent store
│   │   ├── hybrid.py              #   BM25 + dense 하이브리드
│   │   └── metadata_filter.py     #   질의→메타데이터 필터 변환
│   │
│   ├── evaluation/                # 평가 및 트레이싱
│   │   ├── llm_judge.py           #   LLM-as-Judge 4지표 (GPT-5-mini)
│   │   ├── metrics.py             #   Recall@K, MRR (Source/Page level)
│   │   ├── langsmith_tracer.py    #   LangSmith 추적
│   │   └── langfuse_tracer.py     #   Langfuse 추적
│   │
│   ├── prompts/
│   │   └── templates.py           #   ChatPromptTemplate 정의
│   │
│   └── utils/
│       ├── config.py              #   YAML 설정 로더
│       └── env.py                 #   환경변수 관리
│
├── scripts/                       # 유틸리티 스크립트
│   ├── ingest.py                  #   문서 인덱싱 파이프라인
│   ├── eval_retrieval.py          #   RAG E2E 평가 실행
│   ├── build_eval_report.py       #   HTML 대시보드 생성
│   ├── audit_db.py                #   ChromaDB 품질 감사
│   ├── debug_db.py                #   ChromaDB 디버깅
│   ├── generate_eval_set.py       #   평가 데이터셋 생성
│   └── export_langsmith_traces.py #   LangSmith 추적 내보내기
│
├── configs/
│   └── default.yaml               # 전역 설정 (LLM, 임베딩, 검색, 청킹)
│
├── eval_resources/
│   ├── eval_dataset.yaml          # 평가 데이터셋 (20개 질문)
│   ├── eval_results_*.json        # 평가 결과 JSON
│   ├── eval_report.html           # HTML 대시보드
│   └── METRICS.md                 # 지표 정의서
│
├── docs/
│   └── ARCHITECTURE.md            # 시스템 아키텍처 문서
│
├── .claude/                       # Claude Code 설정
│   ├── agents/                    #   eval-runner, rag-debugger, doc-writer
│   ├── skills/                    #   run-eval, build-report, pdf, etc.
│   └── rules/                     #   execution-quality, work-logging
│
├── ai_history/                    # AI 작업 리포트 (날짜별)
├── data/files/                    # 원본 RFP 문서 (Git 제외)
├── chroma_db/                     # ChromaDB 저장소 (Git 제외)
├── results/                       # 실험 결과 (figures, logs, outputs)
└── notebooks/                     # 실험용 주피터 노트북
```

---

## 핵심 워크플로우

```
┌──────────────┐    ┌──────────┐    ┌──────────────────┐    ┌──────────┐
│ analyze_query│───→│ retrieve  │───→│ extract_evidence │───→│ generate │───→ 답변
└──────────────┘    └──────────┘    └──────────────────┘    └──────────┘
     질의 분석          MMR 검색         근거 추출             LLM 생성
```

### 1. analyze_query
- 질의 유형 분류 (single_doc / multi_doc / comparison / out_of_scope)
- 메타데이터 필터 추출 (기관명, 프로젝트명, 연도, 키워드)

### 2. retrieve
- Chroma VectorStore 검색 (MMR, top_k=8, fetch_k=50)
- 3단계 fallback: 필터 적용 → 필터 없음 → 빈 결과

### 3. extract_evidence
- 검색 결과에서 근거 문장 추출 (relevance scoring)

### 4. generate
- LLM 답변 생성 (GPT-5-mini, temperature=0.0)

상세 설명: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## 인덱싱 파이프라인

```
PDF/HWP → parse → clean_documents() → chunk → embed → ChromaDB
                        ↑                ↑        ↑
                  text_cleaner.py    chunker.py  embeddings.py
                  (불릿 정규화,      (1000/200)  (OpenAI)
                   폼 태깅,
                   중복 제거)
```

**처리 흐름:**
1. **파싱**: PDF(pypdf) / HWP(pyhwpx, Windows-only)
2. **클리닝**: 불릿 정규화, 마크다운 제거, 공백 정리, 테이블 플래트닝
3. **청킹**: RecursiveCharacterTextSplitter (chunk_size=1000, overlap=200)
4. **임베딩**: OpenAI text-embedding-3-small (1536d)
5. **저장**: Chroma persistent store (./chroma_db)

---

## 기술 스택

| 카테고리 | 기술 | 버전 | 용도 |
|---------|------|------|------|
| **패키지 관리** | uv | latest | Python 의존성 관리 |
| **프레임워크** | LangChain | 0.3+ | LLM 통합 |
| | LangGraph | 0.2+ | 워크플로우 오케스트레이션 |
| **LLM** | OpenAI GPT-5-mini | - | 답변 생성 및 Judge |
| **임베딩** | text-embedding-3-small | - | 1536d 벡터 |
| **VectorDB** | ChromaDB | 0.5+ | 문서 저장 및 검색 |
| | faiss-cpu | 1.9+ | 대안 검색 엔진 |
| **문서 파싱** | pymupdf4llm | 0.2.9+ | PDF 파서 |
| | pyhwpx | 0.5+ | HWP 파서 (Windows) |
| **검색** | rank-bm25 | 0.2+ | BM25 알고리즘 |
| | kiwipiepy | 0.18+ | 한국어 형태소 분석 |
| **추적/평가** | LangSmith | 0.1+ | 트레이싱 |
| | Langfuse | 2.0+ | 모니터링 |
| **UI** | Streamlit | 1.38+ | 웹 인터페이스 |
| **개발** | pytest | 8.0+ | 테스트 프레임워크 |
| | ruff | 0.7+ | 린터/포매터 |

**특이사항:**
- Python 3.11+ 필수 (onnxruntime 호환성)
- `pyhwpx`는 Windows 전용 (COM automation) → macOS/Linux에서는 HWP 파싱 불가

---

## 평가 시스템

### LLM-as-Judge 지표 (0~5점)

| 지표 | 설명 | 목표 |
|------|------|------|
| **Correctness** | 답변이 기대 답변과 의미적으로 일치하는가 | 4.0+ |
| **Answer Coverage** | 기대 답변의 핵심 정보를 빠짐없이 포함했는가 | 4.0+ |
| **Faithfulness** | 검색된 context에 근거한 답변인가 (환각 없음) | 4.5+ |
| **Context Relevance** | 검색된 문서가 질문에 실제로 관련 있는가 | 4.0+ |

### Retrieval 보조 지표

| 지표 | 설명 | 목표 |
|------|------|------|
| **Recall@K (Source)** | top-K에 정답 문서가 포함된 비율 | 0.85+ |
| **Recall@K (Page)** | top-K에 정답 페이지가 포함된 비율 | 0.75+ |
| **MRR (Source)** | 정답 문서 순위의 역수 평균 | 0.70+ |
| **MRR (Page)** | 정답 페이지 순위의 역수 평균 | 0.60+ |

상세 정의: [`eval_resources/METRICS.md`](eval_resources/METRICS.md)

### 현재 성능 (Baseline)

| 질의 유형 | Correctness | Answer Coverage | Faithfulness | Context Relevance |
|----------|-------------|-----------------|--------------|-------------------|
| single_doc | 4.50 | 4.25 | 4.75 | 4.50 |
| multi_doc | 3.00 | **1.25** ⚠️ | 4.00 | 3.75 |
| comparison | 3.50 | 2.75 | 4.00 | **3.25** ⚠️ |

**알려진 약점:**
- ⚠️ **multi_doc**: Answer Coverage 1.25 → 다중 문서 커버리지 부족
- ⚠️ **comparison**: Context Relevance 3.25 → 비교 대상 문서 동시 검색 어려움

자세한 KPI: [`KPI.md`](KPI.md)

---

## 설정

### configs/default.yaml

```yaml
llm:
  model: "gpt-5-mini"
  temperature: 0.0
  max_tokens: 4096

embedding:
  model: "text-embedding-3-small"
  dimensions: 1536

vectorstore:
  provider: "chroma"
  collection_name: "rfp_docs"
  persist_directory: "./chroma_db"

retriever:
  search_type: "mmr"        # mmr | dense | bm25 | hybrid
  top_k: 8
  fetch_k: 50
  lambda_mult: 0.7          # MMR 다양성 (0=최대 다양성, 1=순수 유사도)
  score_threshold: 0.3

chunking:
  strategy: "recursive"
  chunk_size: 1000
  chunk_overlap: 200
```

**주요 튜닝 포인트:**
- `retriever.top_k`: 검색 결과 개수 (기본 8)
- `retriever.lambda_mult`: MMR 다양성 파라미터 (기본 0.7)
- `chunking.chunk_size`: 청크 크기 (기본 1000)

---

## Claude Code 통합

이 프로젝트는 [Claude Code](https://claude.com/claude-code)와 통합되어 있습니다.

### 에이전트 (`.claude/agents/`)

- **eval-runner**: RAG 평가 실행 및 결과 분석
- **rag-debugger**: 특정 질문의 검색/생성 품질 디버깅
- **doc-writer**: ai_history 작업 보고서 및 문서 작성

### 스킬 (`.claude/skills/`)

- **run-eval**: RAG E2E 평가 실행 및 요약
- **build-report**: 평가 결과 JSON → HTML 대시보드 생성
- **pdf**: PDF 처리 전문 스킬
- **rag-implementation**: RAG 시스템 구현 가이드
- **skill-creator**: 새 스킬 생성 가이드

### 규칙 (`.claude/rules/`)

- **execution-quality.md**: Deep Verification Rule (표면적 실행 방지)
- **work-logging.md**: AI 작업 리포트 작성 프로토콜

---

## 팀 협업 가이드

### Git 워크플로우

```bash
# 1. 새 브랜치 생성
git checkout -b feature/your-feature-name

# 2. 작업 후 커밋
git add <files>
git commit -m "feat: add new feature"

# 3. 푸시
git push origin feature/your-feature-name

# 4. PR 생성 (GitHub)
gh pr create --title "Feature: ..." --body "..."
```

### 커밋 컨벤션

[Conventional Commits](https://www.conventionalcommits.org/) 사용:

- `feat:` - 새 기능
- `fix:` - 버그 수정
- `refactor:` - 코드 리팩토링
- `chore:` - 빌드/설정 변경
- `docs:` - 문서 수정
- `test:` - 테스트 추가/수정

예시:
```bash
git commit -m "feat: add hybrid search with BM25+dense"
git commit -m "fix: resolve HWP parsing error on macOS"
git commit -m "refactor: extract metadata filter logic to separate module"
```

### 코드 품질

```bash
# 린팅 및 포매팅
uv run ruff check .
uv run ruff format .

# 테스트 실행 (예정)
uv run pytest
```

### 작업 리포트

모든 주요 작업은 `ai_history/` 디렉토리에 리포트를 남깁니다:

**파일명 형식:** `YYYYMMDD_HHMM_TaskName_Report.md`

**구조:**
1. User Prompt
2. Thinking Process
3. Execution Result

---

## 개발 로드맵

### Phase 1: 기반 구축 ✅
- [x] PDF/HWP 파싱 파이프라인
- [x] LangGraph 워크플로우
- [x] MMR 검색 시스템
- [x] LLM-as-Judge 평가

### Phase 2: 성능 개선 🔄
- [ ] multi_doc Answer Coverage 개선 (목표: 1.25 → 3.5+)
- [ ] comparison Context Relevance 개선 (목표: 3.25 → 4.0+)
- [ ] Hybrid 검색 (BM25 + dense) 활성화
- [ ] 청크 전략 최적화 (semantic chunking)

### Phase 3: 기능 확장 📅
- [ ] 테이블 추출 및 구조화
- [ ] 다중 문서 비교 UI
- [ ] 실시간 스트리밍 답변
- [ ] 사용자 피드백 수집 시스템

### Phase 4: 프로덕션 준비 📅
- [ ] 단위 테스트 커버리지 80%+
- [ ] CI/CD 파이프라인 (GitHub Actions)
- [ ] Docker 컨테이너화
- [ ] 성능 벤치마크 (latency, throughput)

---

## 문제 해결

### HWP 파일이 파싱되지 않아요 (macOS/Linux)

`pyhwpx`는 Windows 전용입니다. macOS/Linux에서는 HWP → PDF 변환 후 사용하세요.

```bash
# 대안 1: 온라인 변환기 사용
# 대안 2: Windows VM에서 ingest.py 실행
```

### ChromaDB가 초기화되지 않아요

```bash
# DB 완전 삭제 후 재생성
rm -rf chroma_db/
uv run python scripts/ingest.py --reset
```

### 평가 점수가 너무 낮아요

1. 검색 품질 확인:
   ```bash
   uv run python scripts/debug_db.py
   ```

2. Context Relevance 점검 (eval_report.html)
3. 설정 튜닝:
   - `retriever.top_k` 증가 (8 → 12)
   - `retriever.lambda_mult` 조정 (0.7 → 0.5, 더 다양한 결과)

---

## 라이선스

이 프로젝트는 교육 및 연구 목적으로 개발되었습니다.

---

## 기여

이슈 및 PR 환영합니다! 기여하기 전에 [`CLAUDE.md`](CLAUDE.md)를 참고하세요.

**팀원:**
- AI_7-team (CodeIt Sprint AI 엔지니어링 과정)

---

## 참고 문서

- [아키텍처 문서](docs/ARCHITECTURE.md)
- [평가 지표 정의](eval_resources/METRICS.md)
- [KPI 및 성능 목표](KPI.md)
- [Claude Code 설정](CLAUDE.md)
- [프로젝트 개요](PROJECT_BRIEF.md)