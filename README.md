# 입찰메이트 RFP 챗봇 v17 - 사용 설명서

RFP(제안요청서) 문서 기반 지능형 질의응답 시스템

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![OpenAI](https://img.shields.io/badge/OpenAI-gpt--5--mini-green.svg)](https://openai.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.20+-red.svg)](https://streamlit.io)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 목차

1. [프로젝트 소개](#-프로젝트-소개)
2. [내 작업물 변경사항](#-내-작업물-변경사항)
3. [핵심 기능](#-핵심-기능)
4. [프로젝트 구조](#-프로젝트-구조)
5. [빠른 시작](#-빠른-시작)
6. [상세 사용법](#-상세-사용법)
7. [사용 예시](#-사용-예시)
8. [기술 스택](#-기술-스택)
9. [모듈 설명](#-모듈-설명)
10. [트러블슈팅](#-트러블슈팅)

---

## 프로젝트 소개

**입찰메이트**는 RFP(제안요청서) 문서를 기반으로 한 AI 기반 질의응답 시스템입니다. 대규모 입찰 문서에서 필요한 정보를 빠르고 정확하게 찾아줍니다.

---

## 내 작업물 변경사항

### 2026-02-14 반영 내용

- 평가 리소스 경로를 `eval/`에서 `eval_resources/`로 정리
- 평가 모듈 신설: `src/evaluation/`
- 평가/실험 스크립트 추가: `scripts/eval_retrieval.py`, `scripts/build_eval_report.py`
- 통합 전처리 경로 추가: `src/parsers/preprocessor.py`, `scripts/build_unified_corpus.py`
- 실험 기록 문서 추가: `docs/EXPERIMENT_LOG.md`

---

## 핵심 기능

| 기능 | 설명 |
|:---|:---|
| **LLM 기반 질문 파싱** | gpt-5-mini로 질문 의도 분류 (기관 조회, 랭킹, 필터링, 카테고리, 검색) |
| **후속 질문 지원** | 대화 컨텍스트를 통한 "그거 언제야?", "사업명은?" 등 자연스러운 대화 |
| **멀티소스 통합** | CSV + HWP + PDF 문서를 마크다운으로 통합 변환 |
| **정교한 필터링** | "5억에서 10억 사이", "10억 이상" 등 범위 질문 지원 |
| **초고속 검색** | ChromaDB 벡터 DB + cosine similarity 기반 검색 |

---

## 프로젝트 구조

```
AI_7-team/
├── app/                          # Streamlit 웹 UI
│   └── main.py                   # 채팅 인터페이스
├── src/                          # 핵심 소스 코드
│   ├── graph/                    # LangGraph 워크플로우
│   │   ├── state.py             # 상태 정의 (QueryIntent, OrgInfo 등)
│   │   ├── nodes.py             # 질문 파싱, 답변 생성 노드
│   │   └── workflow.py          # 메인 RAG 챗봇 클래스
│   ├── parsers/                 # 문서 로더 및 파서
│   │   ├── csv_loader.py         # CSV 처리
│   │   ├── pdf_loader.py        # PDF 처리 (pdfplumber)
│   │   ├── hwp_loader.py        # HWP 처리 (LibreOffice → PDF 변환)
│   │   ├── text_cleaner.py      # 텍스트 정제
│   │   └── chunker.py          # 문서 청킹
│   ├── retrievers/              # 검색 시스템
│   │   ├── embeddings.py        # OpenAI 임베딩
│   │   ├── vectorstore.py       # ChromaDB 벡터 저장소
│   │   ├── metadata_filter.py   # 메타데이터 필터링
│   ├── evaluation/              # 평가 및 트레이싱
│   │   ├── llm_judge.py         # LLM-as-Judge 4지표
│   │   ├── metrics.py           # Retrieval 지표 (Recall@K, MRR)
│   │   ├── langsmith_tracer.py  # LangSmith 트레이싱
│   │   └── langfuse_tracer.py   # Langfuse 메트릭 수집
│   ├── prompts/                 # 프롬프트 템플릿
│   │   └── templates.py         # RAG 프롬프트
│   └── utils/                  # 유틸리티
│       ├── config.py            # 설정 관리
│       └── helpers.py          # 헬퍼 함수
├── scripts/                      # 유틸리티 스크립트
│   ├── rebuild_db.py            # 벡터 DB 재구축
│   ├── build_unified_corpus.py  # CSV+원본 통합 코퍼스 생성
│   ├── eval_retrieval.py        # 평가 실행 스크립트
│   └── build_eval_report.py     # 평가 리포트 생성
├── tests/                       # 테스트 코드
│   └── test_conversation.py     # 대화 기능 테스트
├── configs/                     # 설정 파일
│   └── default.yaml             # 기본 설정
├── docs/                       # 문서
│   ├── DOCUMENTATION.md          # 통합 기술 문서
│   ├── slides.html              # 프레젠테이션 슬라이드
│   ├── USAGE.md                 # 사용 방법
│   ├── USAGE_NEW.md             # 새 사용법
│   └── ARCHITECTURE.md          # 아키텍처 설계
├── eval_resources/              # 평가 관련 리소스
│   ├── METRICS.md               # 평가 지표
│   └── eval_dataset.yaml        # 평가 데이터셋
├── data/                        # 데이터 파일 (Git 제외)
├── chroma_db/                  # 벡터 DB (Git 제외)
├── .env.example                 # 환경 변수 예시
├── requirements.txt              # Python 의존성
└── README.md                    # 이 파일
```

---

## 빠른 시작

### 1. 저장소 클론

```bash
git clone -b feature/jh2 https://github.com/Loah-Lee/AI_7-team.git
cd AI_7-team
```

### 2. 사전 요구사항 확인

```bash
# Python 3.10 이상 필요
python --version
```

### 3. 가상 환경 설정

```bash
# 가상 환경 생성
python -m venv venv

# 가상 환경 활성화
source venv/bin/activate  # Linux/macOS
# 또는
venv\Scripts\activate     # Windows
```

### 4. 의존성 설치

```bash
pip install -r requirements.txt
```

### 5. 환경 변수 설정

```bash
# 환경 변수 파일 생성
cp .env.example .env

# .env 파일을 열어 OPENAI_API_KEY 입력
vi .env  # 또는 nano, code 등 선호하는 에디터 사용
```

**`.env` 파일 내용:**
```env
OPENAI_API_KEY=sk-your-api-key-here
CHROMA_DB_PATH=./data/chroma_db_v17
DEFAULT_MODEL=gpt-5-mini
REASONING_MODEL=gpt-5-mini
EMBEDDING_MODEL=text-embedding-3-small
```

### 6. 실행

#### Streamlit 웹 버전 (권장)
```bash
streamlit run app/main.py
```
브라우저에서 `http://localhost:8501` 접속

#### CLI 버전
```bash
python -m src.graph.workflow
```

---

## 상세 사용법

### 질문 유형별 사용법

| 질문 유형 | 예시 | 처리 방식 |
|:---|:---|:---|
| **기관 조회** | "고려대학교 사업비는?" | org 레지스트리에서 직접 검색 |
| **랭킹 조회** | "TOP5 기관은?" | 사업비 순 정렬 |
| **범위 필터링** | "5억에서 10억 사이" | min/max 조건 필터링 |
| **카테고리 검색** | "IT 관련 사업?" | 사업명 키워드 검색 |
| **후속 질문** | "그거 언제야?" | 대화 컨텍스트 활용 |

### DB 재구축

데이터가 변경되었을 때 벡터 DB를 재구축합니다:

```bash
python scripts/rebuild_db.py
```

### 통합 전처리 (CSV + 원본 문서)

CSV 메타데이터와 원본(HWP/PDF)을 매칭해 통합 마크다운/매니페스트를 생성합니다.

```bash
python scripts/build_unified_corpus.py --input-dir data/files --output-dir data/processed
```

### 테스트 실행

```bash
# 대화 기능 테스트
python tests/test_conversation.py
```

---

## 사용 예시

### 1. 기관별 조회
```
Q: 고려대학교 사업비는?
A: 약 141.1억 원입니다.
```

### 2. 랭킹 조회
```
Q: 사업비가 가장 많은 3곳은?
A: 1. 서울특별시: 5,000억 원
   2. 고려대학교: 141.1억 원
   3. 서울시립대학교: 85억 원
```

### 3. 범위 필터링
```
Q: 사업비가 5억에서 10억 사이인 기관은?
A: 부산광역시, 인천광역시 등 5개 기관
```

### 4. 후속 질문 (대화 컨텍스트)
```
Q: 고려대학교 사업비는?
A: 약 141.1억 원입니다.

Q: 그거 언제까지야?
A: 2024년 12월 31일까지입니다.

Q: 사업명은?
A: 스마트캠퍼스 구축입니다.
```

---

## 기술 스택

| 분류 | 기술 | 버전 |
|:---|:---|:---|
| **언어** | Python | 3.10+ |
| **LLM** | OpenAI gpt-5-mini | latest |
| **추론 LLM** | OpenAI gpt-5-mini | latest |
| **임베딩** | OpenAI text-embedding-3-small | 1536 dim |
| **벡터 DB** | ChromaDB | 0.4.0+ |
| **PDF 처리** | pdfplumber | 0.10.0+ |
| **HWP 처리** | pyhwpx | latest |
| **웹 프레임워크** | Streamlit | 1.20+ |
| **한국어 임베딩** | sentence-transformers | 2.2.0+ (폴백) |
| **데이터 처리** | pandas | 2.0.0+ |

---

## 모듈 설명

### 질문 파싱 시스템
- **위치**: `src/graph/nodes.py`
- **클래스**: `QueryIntentParser`
- **역할**: LLM을 활용하여 사용자 질문의 의도를 분석하고 구조화

### 대화 컨텍스트 관리
- **위치**: `src/graph/state.py`
- **클래스**: `ConversationContext`
- **역할**: 대화 기록을 유지하고 후속 질문 처리

### 문서 처리 파이프라인
- **위치**: `src/parsers/`
- **지원 형식**: CSV, PDF, HWP
- **출력**: 마크다운 형식으로 통합

### 벡터 검색 엔진
- **위치**: `src/retrievers/vectorstore.py`
- **기술**: ChromaDB + OpenAI Embeddings
- **유사도**: cosine similarity

### 답변 생성
- **위치**: `src/graph/nodes.py`
- **클래스**: `RFPAnswerGenerator`
- **역할**: RAG 기반으로 간결하고 정확한 답변 생성

### 웹 UI
- **위치**: `app/main.py`
- **기술**: Streamlit
- **기능**: 실시간 채팅 인터페이스

---

## 트러블슈팅

### ChromaDB 오류

```bash
# DB 재구축으로 해결
python scripts/rebuild_db.py
```

### 임베딩 오류

```bash
# API 키 확인
echo $OPENAI_API_KEY

# 또는 .env 파일 확인
cat .env
```

### PDF 파싱 오류

```bash
# pdfplumber 재설치
pip uninstall pdfplumber
pip install pdfplumber>=0.10.0
```

### HWP 파싱 오류

```bash
# pyhwpx 재설치
pip uninstall pyhwpx
pip install pyhwpx
```

### Streamlit 실행 오류

```bash
# Streamlit 재설치
pip uninstall streamlit
pip install streamlit>=1.20.0
```

---

## 추가 문서

- [통합 기술 문서](docs/DOCUMENTATION.md) - 9개 챕터로 구성된 상세 기술 문서
- [프레젠테이션 슬라이드](docs/slides.html) - 브라우저에서 바로 보기
- [상세 사용법](docs/USAGE.md)
- [아키텍처 설계](docs/ARCHITECTURE.md)
- [평가 지표](eval_resources/METRICS.md)
- [실험 변경 보고서](docs/EXPERIMENT_LOG.md) - 성능 개선 실험 로그

---

## 라이선스

MIT License

---

**7팀** | 2026년 2월 11일 | [GitHub](https://github.com/Loah-Lee/AI_7-team)
