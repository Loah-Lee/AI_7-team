# RFP RAG System Project Brief

## Project Overview

**Project Name:** RFP Document Analysis RAG System
**Company Context:** BidMate (입찰메이트) - B2G Bid Consulting Startup
**Project Duration:** Sprint-based development with final presentation

### Business Problem
BidMate provides public bid consulting services. Daily, hundreds of RFPs (Request for Proposals) are published on platforms like "나라장터". Each RFP can be dozens of pages long, making it impossible for company representatives to read them all. BidMate's consultants need to quickly identify key information (requirements, budget, submission methods, target institutions) to recommend suitable bidding opportunities to clients.

### Solution Goal
Build an internal RAG (Retrieval-Augmented Generation) system that efficiently extracts and summarizes RFP document content based on user queries, enabling consultants to focus on consulting rather than document review.

---

## Technical Stack

### Available Models
- ✅ OK: gpt-5
- ✅ OK: gpt-5-mini
- ✅ OK: gpt-5-nano

### Embedding
- OpenAI Embedding API (text-embedding-3-small 등)

### Vector DB
- FAISS 또는 Chroma

### Product Framework
- **LangGraph** 기반 RAG 파이프라인 구성
- 노드 단위로 파서, 리트리버, 생성기 등을 그래프로 연결

### 실험 UI
- **Streamlit** 기반 실험/데모 인터페이스 구현
- 질의응답 테스트, 리트리버 성능 비교, 결과 시각화

### 실험 평가 및 추적
- **LangSmith** — LangGraph/LangChain 실행 트레이싱, 프롬프트 실험 추적
- **Langfuse** — 평가 메트릭 수집, 비용/레이턴시 모니터링

---

## Technical Requirements

### Data
- **Dataset:** 100 real RFP documents with metadata
- **Formats:** HWP and PDF files
- **Metadata:** Provided in `data_list.csv`
- **Location:** Google Drive > Project > Intermediate Project > Original Data

### Core Functionality
1. **Document Processing**
   - Load both HWP and PDF formats
   - Process document metadata
   - Implement document chunking strategy

2. **RAG System Components**
   - **Retrieval:** Embedding generation, vector DB setup, metadata filtering
   - **Generation:** LLM selection, response optimization, conversation history management
   - **Evaluation:** Performance metrics and testing framework (LangSmith / Langfuse)

3. **Key Features**
   - Q&A based on RFP documents
   - Multi-document information synthesis
   - Conversation context maintenance
   - Handling of out-of-scope queries

---

## 모듈 구조 (GitHub 협업용)

팀원 간 병렬 작업이 가능하도록 다음과 같이 모듈화하여 개발합니다.

```
project/
├── parsers/          # 문서 파싱 모듈 (HWP, PDF 로더 및 청킹)
├── retrievers/       # 리트리버 모듈 (임베딩, 벡터DB, 메타데이터 필터링)
├── evaluation/       # 평가 모듈 (LangSmith/Langfuse 연동, KPI 측정)
├── graph/            # LangGraph 워크플로우 (노드 정의, 그래프 구성)
├── app/              # Streamlit 앱 (실험 UI, 데모)
├── prompts/          # 프롬프트 템플릿
├── utils/            # 공통 유틸리티
├── data/             # RFP 문서 저장소
├── configs/          # 설정 파일 (모델, DB, API 키 경로 등)
└── tests/            # 테스트 코드
```

| 모듈 | 담당 역할 | 비고 |
|------|----------|------|
| `parsers/` | HWP/PDF 파싱, 청킹 전략 | 독립 개발 가능 |
| `retrievers/` | 임베딩, 벡터DB, 검색 최적화 | 독립 개발 가능 |
| `evaluation/` | KPI 측정, 실험 추적 | LangSmith/Langfuse 연동 |
| `graph/` | LangGraph 워크플로우 조립 | parsers + retrievers 통합 |
| `app/` | Streamlit 실험 UI | graph 모듈 호출 |

---

## Implementation Phases

### 1. Setup & Planning
- [ ] Team role assignment (PM, Parser, Retriever, Graph/Generation)
- [ ] Timeline creation and task distribution
- [ ] GitHub repository 세팅 및 모듈 구조 생성
- [ ] LangSmith / Langfuse 프로젝트 생성

### 2. Data Processing (`parsers/`)
- [ ] Load HWP and PDF documents
- [ ] Parse and structure metadata from `data_list.csv`
- [ ] Implement chunking strategy
  - Define chunk size and overlap
  - (Advanced) Semantic chunking based on RFP format

### 3. Embedding & Vector DB (`retrievers/`)
- [ ] Select embedding model (text-embedding-3-small 등)
- [ ] Generate embeddings for all chunks
- [ ] Set up vector database (FAISS / Chroma)
- [ ] Implement metadata filtering for multi-document search

### 4. Retrieval Implementation (`retrievers/`)
- [ ] Implement baseline naive retrieval
- [ ] Add metadata filtering (handle fuzzy user inputs for institution names, project names)
- [ ] Experiment with retrieval techniques:
  - Top-k value tuning
  - MMR (Maximum Marginal Relevance)
  - Hybrid Search
  - (Advanced) Multi-Query, Re-Ranking

### 5. LangGraph Workflow (`graph/`)
- [ ] 노드 설계: 질의 분석 → 리트리버 → 근거 추출 → 답변 생성
- [ ] LangGraph 그래프 조립 및 상태 관리
- [ ] Configure generation parameters (temperature, top_p, max_tokens)
- [ ] Develop prompt engineering strategy:
  - Faithful to retrieved context
  - Exclude irrelevant information
  - Adjust tone and style
  - Optimize token usage
- [ ] Implement conversation history management

### 6. Evaluation (`evaluation/`)
- [ ] LangSmith 트레이싱 연동
- [ ] Langfuse 메트릭 수집 설정
- [ ] KPI 측정 자동화 (상세 KPI는 [KPI.md](KPI.md) 참조)
- [ ] Create diverse question sets
- [ ] Measure response time (speed vs. quality trade-off)

### 7. Streamlit 실험 UI (`app/`)
- [ ] 질의응답 인터페이스 구현
- [ ] 리트리버 성능 비교 화면
- [ ] 실험 결과 시각화 대시보드

### 8. Documentation & Presentation
- [ ] Write analysis report with process, results, improvements, and decision rationale
- [ ] Prepare 20-minute team presentation (+ 5 min Q&A)
- [ ] All team members participate in presentation

---

## Example Queries

```
1. "국민연금공단이 발주한 이러닝시스템 관련 사업 요구사항을 정리해 줘."
   (Summarize the requirements for the e-learning system project issued by National Pension Service.)

2. "콘텐츠 개발 관리 요구 사항에 대해서 더 자세히 알려 줘."
   (Tell me more details about content development management requirements.)

3. "교육이나 학습 관련해서 다른 기관이 발주한 사업은 없나?"
   (Are there any education or learning-related projects from other institutions?)

4. "기초과학연구원 극저온시스템 사업 요구에서 AI 기반 예측에 대한 요구사항이 있나?"
   (Are there requirements for AI-based prediction in the IBS cryogenic system project?)

5. "한국 원자력 연구원에서 선량 평가 시스템 고도화 사업을 발주했는데, 이 사업이 왜 추진되는지 목적을 알려 줘."
   (KAERI issued a dose assessment system upgrade project - tell me the purpose.)

6. "고려대학교 차세대 포털 시스템 사업이랑 광주과학기술원의 학사 시스템 기능개선 사업을 비교해 줄래?"
   (Can you compare Korea University's next-gen portal system and GIST's academic system improvement project?)
```

---

## Deliverables

### GitHub Repository (Due: D-1, 19:00)
- Complete RAG system code
- README with:
  - Project overview
  - Setup instructions
  - Usage guide
  - Report PDF download link
  - Individual collaboration log links

### Analysis Report (Due: D-1, 19:00)
- PDF format
- Include: process, results, achievements, improvements, decision rationale
- Can be presentation slides or separate report

### Individual Collaboration Logs (Due: Final day, 23:50)
- Daily entries with:
  - What you planned to do today
  - What you accomplished/didn't accomplish
  - Collaboration reflections
  - Code, insights, challenges, mistakes
  - Your contribution to the team
- Link in README (Notion, blog, or PDF)

---

## Team Roles (Recommended)

| Role | Responsibilities |
|------|------------------|
| **Project Manager** | Sprint management, meeting facilitation, KPI 모니터링, 평가 총괄 |
| **Parser** | HWP/PDF 파싱, 청킹 전략, 메타데이터 처리 |
| **Retriever** | 임베딩, 벡터DB, 메타데이터 필터링, 검색 최적화 |
| **Graph / Generation** | LangGraph 워크플로우, 프롬프트 엔지니어링, Streamlit UI |

---

## Evaluation Criteria

### Team Evaluation
- Project planning and topic selection
- Data preprocessing and exploration
- Model selection and design
- RAG 파이프라인 구성 및 최적화
- Code quality and documentation
- Business insights from results
- Presentation quality

### Individual Evaluation
- Topic ideation and feedback
- Data preprocessing contribution
- 담당 모듈 개발 기여도
- Timeline adherence and task completion
- Presentation participation
- Collaboration log quality

---

## Important Notes

### Security
- ⚠️ **Do NOT commit API keys or SSH keys to GitHub**
- ⚠️ **Do NOT share original RFP documents externally** (NDA requirement)
- ✅ Processed results, code, reports are shareable

### Resources
- **OpenAI API:** gpt-5, gpt-5-mini, gpt-5-nano, text-embedding-3-small (keys in Discord)
- **Data Access:** Google Drive shared folder

### Development Tips
- Implement baseline first, then iterate improvements
- Balance quality vs. speed vs. cost
- Document all decisions and experiments
- LangSmith로 실험 트레이싱을 꼼꼼히 남길 것
- Ask mentors for help early and often

---

## Success Metrics
- Accurate single-document information extraction
- Effective multi-document synthesis
- Contextual follow-up question handling
- Proper rejection of out-of-scope queries
- Fast response time without sacrificing quality
- KPI 목표 달성 (상세: [KPI.md](KPI.md))
- Well-documented decision-making process
- Effective team collaboration

---

## Project Timeline
1. **OT Day:** Project kickoff
2. **Main Period:** OT → Final day D-1
3. **Presentation:** Final day
4. **Post-Presentation:** Mentoring, feedback, optional refactoring

---

*This project simulates a real-world AI engineering challenge in the B2G consulting domain. Focus on thoughtful experimentation, clear documentation, and effective teamwork.*
