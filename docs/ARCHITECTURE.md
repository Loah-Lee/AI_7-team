# 입찰메이트 v17 아키텍처

## 시스템 개요

```
┌─────────────────────────────────────────────────────┐
│           Streamlit Web UI (app/main.py)       │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│     RAG Chatbot (src/graph/workflow.py)      │
│  - QueryIntentParser                          │
│  - ConversationContext                        │
│  - RFPAnswerGenerator                         │
└──┬──────────────────┬──────────────┬────────┘
   │                  │              │
   ▼                  ▼              ▼
┌─────────┐    ┌──────────┐  ┌──────────┐
│ Parsers │    │Retrievers│  │ Prompts  │
│ - CSV   │    │- Vector  │  │ Templates│
│ - PDF   │    │  Store   │  │          │
│ - HWP   │    │- Embedding│  └──────────┘
└─────────┘    └──────────┘
```

## 핵심 컴포넌트

### 1. 질문 파싱 (Query Parsing)
- **QueryIntentParser**: LLM 기반 질문 의도 분석
- **ConversationContext**: 대화 기록 및 후속 질문 처리

### 2. 문서 처리 (Document Processing)
- **CSVMarkdownConverter**: CSV → 마크다운
- **PDFMarkdownConverter**: PDF → 마크다운
- **HWPMarkdownConverter**: HWP → 마크다운

### 3. 검색 (Retrieval)
- **VectorStore**: ChromaDB 기반 벡터 검색
- **OpenAI Embeddings**: text-embedding-3-small

### 4. 답변 생성 (Generation)
- **RFPAnswerGenerator**: 간결한 RFP 답변 생성
- **RFP_SYSTEM_PROMPT**: 핵심 정보 추출 프롬프트

## 데이터 흐름

```
1. 사용자 질문 입력
       ↓
2. QueryIntentParser 분석
       ↓
3. ConversationContext 확인 (후속 질문?)
       ↓
4. VectorStore 검색
       ↓
5. RFPAnswerGenerator 답변 생성
       ↓
6. 답변 출력 + 대화 기록 저장
```
