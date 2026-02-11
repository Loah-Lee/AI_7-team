# 입찰메이트 RFP 챗봇 v17 - 모듈화 아키텍처

RFP(제안요청서) 문서 기반 지능형 질의응답 시스템

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![OpenAI](https://img.shields.io/badge/OpenAI-gpt--4o--mini-green.svg)](https://openai.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.20+-red.svg)](https://streamlit.io)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 🎯 핵심 기능

- **🤖 LLM 기반 질문 파싱**: gpt-4o-mini로 질문 의도 분류 (기관 조회, 랭킹, 필터링, 카테고리, 검색)
- **💬 후속 질문 지원**: 대화 컨텍스트를 통한 "그거 언제야?", "사업명은?" 등 자연스러운 대화
- **📊 멀티소스 통합**: CSV + HWP + PDF → 마크다운 통합 변환
- **🎯 정교한 필터링**: "5억에서 10억 사이", "10억 이상" 등 범위 질문 지원
- **⚡ 초고속 검색**: ChromaDB 벡터 DB + cosine similarity

## 📁 프로젝트 구조

```
AI_7-team/
├── app/                          # Streamlit 웹 UI
│   └── main.py
├── src/                          # 핵심 소스
│   ├── graph/                    # LangGraph 워크플로우
│   │   ├── state.py             # 상태 정의 (QueryIntent, OrgInfo 등)
│   │   ├── nodes.py             # 질문 파싱, 답변 생성 노드
│   │   └── workflow.py          # 메인 RAG 챗봇 클래스
│   ├── parsers/                 # 문서 로더
│   │   ├── csv_loader.py         # CSV 처리
│   │   ├── pdf_loader.py        # PDF 처리 (pdfplumber)
│   │   ├── hwp_loader.py        # HWP 처리
│   │   ├── text_cleaner.py      # 텍스트 정제
│   │   └── chunker.py          # 청킹
│   ├── retrievers/              # 검색 시스템
│   │   ├── embeddings.py        # OpenAI 임베딩
│   │   ├── vectorstore.py       # ChromaDB
│   │   ├── hybrid.py            # 하이브리드 검색
│   │   └── metadata_filter.py   # 메타데이터 필터
│   ├── prompts/                 # 프롬프트 템플릿
│   │   └── templates.py
│   └── utils/                  # 유틸리티
│       ├── config.py            # 설정, 상수
│       └── helpers.py          # 헬퍼 함수
├── scripts/                      # 유틸리티 스크립트
│   └── rebuild_db.py
├── tests/                       # 테스트
│   └── test_conversation.py
├── configs/                     # 설정 파일
│   └── default.yaml
├── docs/                       # 문서
│   ├── USAGE.md                 # 사용 방법
│   └── ARCHITECTURE.md          # 아키텍처
├── eval/                        # 평가 (사용자 생성)
├── data/                        # 데이터 (Git 제외)
├── chroma_db/                  # 벡터 DB (Git 제외)
├── .env.example                 # 환경 변수 예시
├── requirements.txt              # 의존성
└── README.md
```

## 🚀 빠른 시작

### 1. 저장소 클론

```bash
git clone -b feature/jh2 https://github.com/Loah-Lee/AI_7-team.git
cd AI_7-team
```

### 2. 가상 환경 설정

```bash
# 가상 환경 생성
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 또는
venv\Scripts\activate  # Windows
```

### 3. 의존성 설치

```bash
pip install -r requirements.txt
```

### 4. 환경 변수 설정

```bash
# 환경 변수 파일 생성
cp .env.example .env

# .env 파일을 열어 OPENAI_API_KEY 입력
vi .env  # 또는 nano, code 등
```

### 5. 실행

#### Streamlit 웹 버전
```bash
streamlit run app/main.py
```

브라우저에서 `http://localhost:8501` 접속

#### CLI 버전
```bash
python -m src.graph.workflow
```

## 💬 사용 예시

### 기관별 조회
```
Q: 고려대학교 사업비는?
A: 약 141.1억 원입니다.
```

### 랭킹 조회
```
Q: 사업비가 가장 많은 3곳은?
A: 1. 서울특별시: 5,000억 원
   2. 고려대학교: 141.1억 원
   3. 서울시립대학교: 85억 원
```

### 범위 필터링
```
Q: 사업비가 5억에서 10억 사이인 기관은?
A: 부산광역시, 인천광역시 등 5개 기관
```

### 후속 질문 (대화 컨텍스트)
```
Q: 고려대학교 사업비는?
A: 약 141.1억 원입니다.

Q: 그거 언제까지야?
A: 2024년 12월 31일까지입니다.

Q: 사업명은?
A: 스마트캠퍼스 구축입니다.
```

## 🛠 기술 스택

| 분류 | 기술 |
|:---|:---|
| **임베딩** | OpenAI text-embedding-3-small (1536 dim) |
| **LLM** | gpt-4o-mini (기본), gpt-5-mini (추론) |
| **벡터 DB** | ChromaDB (cosine similarity) |
| **PDF 처리** | pdfplumber |
| **HWP 처리** | pyhwpx, oletools |
| **웹 프레임워크** | Streamlit 1.20+ |
| **언어** | Python 3.10+ |

## 📝 주요 모듈 설명

| 모듈 | 파일 | 역할 |
|:---|:---|:---|
| **질문 파싱** | `src/graph/nodes.py` | QueryIntentParser: LLM 기반 질문 의도 분석 |
| **대화 컨텍스트** | `src/graph/state.py` | ConversationContext: 대화 기록 및 후속 질문 처리 |
| **문서 처리** | `src/parsers/` | CSV/PDF/HWP → 마크다운 변환 |
| **벡터 검색** | `src/retrievers/vectorstore.py` | ChromaDB 기반 문서 검색 |
| **답변 생성** | `src/graph/nodes.py` | RFPAnswerGenerator: 간결한 답변 생성 |
| **웹 UI** | `app/main.py` | Streamlit 기반 채팅 인터페이스 |

## 🧪 테스트

```bash
# 대화 기능 테스트
python tests/test_conversation.py

# DB 재구축
python scripts/rebuild_db.py
```

## 📖 문서

- [사용 방법](docs/USAGE.md) - 상세 사용 가이드
- [아키텍처](docs/ARCHITECTURE.md) - 시스템 설계

## 📜 라이선스

MIT License

---

**7팀** | 2026년 2월 11일 | [GitHub](https://github.com/Loah-Lee/AI_7-team)
