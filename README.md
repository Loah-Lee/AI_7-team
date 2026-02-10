# AI_7-team: RFP-RAG-Analyzer (BiddingMate)
> **100여 개의 RFP(제안요청서) 분석 및 요약을 위한 RAG 시스템 구축 프로젝트**

본 프로젝트는 복잡한 입찰 공고문(RFP)을 효율적으로 분석하여 컨설턴트의 의사결정을 돕는 AI 도구를 개발합니다.

---

## 빠른 시작

### 1. 환경 설정

```bash
# 의존성 설치 (uv 사용)
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
```

### 3. Streamlit 앱 실행

```bash
# 기본 실행
streamlit run app/main.py

# 포트/주소 지정
streamlit run app/main.py --server.port 8501 --server.address 0.0.0.0
```

### 4. DB 품질 감사 (선택)

```bash
uv run python scripts/audit_db.py --label before
```

---

## 폴더 구조

```
.
├── app/                 # Streamlit UI (entry: main.py)
├── configs/             # 설정 파일 (default.yaml)
├── data/files/          # 원본 PDF/HWP 문서 (Git 제외)
├── scripts/             # 유틸리티 스크립트
│   ├── ingest.py        #   문서 파싱 → 클리닝 → 청킹 → 임베딩 → ChromaDB 저장
│   └── audit_db.py      #   ChromaDB 품질 감사
├── src/
│   ├── graph/           # LangGraph 워크플로우 (state, nodes, workflow)
│   ├── parsers/         # PDF/HWP 파서, 청커, 텍스트 클리너
│   ├── prompts/         # 프롬프트 템플릿
│   ├── retrievers/      # 임베딩, 벡터스토어, 하이브리드 검색
│   ├── evaluation/      # 평가 메트릭 및 트레이싱 (LangSmith/Langfuse)
│   └── utils/           # 설정 로더, 환경변수
├── notebooks/           # 실험용 주피터 노트북
├── ai_history/          # AI 작업 리포트
└── chroma_db/           # ChromaDB 영속 저장소 (Git 제외)
```

---

## 인덱싱 파이프라인

```
PDF/HWP → parse → clean_documents() → chunk → embed → ChromaDB
                        ↑
              text_cleaner.py
              (불릿 정규화, markdown 제거, 공백 정규화)
```