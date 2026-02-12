# 입찰메이트 v17 - 사용법

## 🚀 빠른 시작

### 1. 사전 준비

```bash
# Python 3.10+ 설치 확인
python --version

# Git 저장소 클론
cd /path/to/workspace
git clone https://github.com/Loah-Lee/AI_7-team.git
cd AI_7-team
```

### 2. 가상 환경 설정

```bash
# 가상 환경 생성
python -m venv venv

# 활성화
source venv/bin/activate  # Linux/macOS
# 또는
.\venv\Scripts\activate  # Windows
```

### 3. 의존성 설치

```bash
# 모든 의존성 설치
pip install -r requirements.txt
```

### 4. 환경 변수 설정

```bash
# .env 파일 생성
cp .env.example .env

# .env 파일을 열어 OPENAI_API_KEY 입력
vi .env  # 또는 nano, code 등
```

### 5. 데이터 준비

```bash
# 데이터 폴더 확인
ls data/

# CSV 파일이 있는지 확인
ls data/*.csv

# PDF/HWP 파일이 있는지 확인
ls data/*.pdf data/*.hwp
```

### 6. 실행

#### 웹 버전 (Streamlit)

```bash
streamlit run app/main.py
```

브라우저에서 `http://localhost:8501` 접속

#### CLI 버전

```bash
python -m src.graph.workflow
```

## 📁 프로젝트 구조

```
AI_7-team/
├── app/                    # Streamlit 웹 UI
│   └── main.py
├── src/                    # 핵심 소스
│   ├── graph/             # 워크플로우
│   │   ├── state.py      # 상태, 데이터클래스
│   │   ├── nodes.py      # 파싱, 생성 노드
│   │   └── workflow.py   # 메인 로직
│   ├── parsers/           # 문서 파서
│   │   ├── csv_loader.py
│   │   ├── pdf_loader.py
│   │   └── hwp_loader.py
│   ├── retrievers/        # 검색 시스템
│   │   └── vectorstore.py
│   ├── prompts/           # 프롬프트
│   │   └── templates.py
│   └── utils/            # 유틸리티
│       ├── config.py
│       └── helpers.py
├── scripts/               # 유틸리티 스크립트
│   └── rebuild_db.py
├── tests/                 # 테스트
│   └── test_conversation.py
├── configs/               # 설정
│   └── default.yaml
├── docs/                 # 문서
├── data/                 # 데이터 (Git 제외)
├── chroma_db/            # 벡터 DB (Git 제외)
└── requirements.txt        # 의존성
```

## 🎯 주요 질문 타입

| 질문 유형 | 예시 | 처리 방식 |
|:---|:---|:---|
| 기관 조회 | "고려대학교 사업비는?" | org 레지스트리에서 직접 검색 |
| 랭킹 | "TOP5 기관은?" | 사업비 순 정렬 |
| 범위 필터 | "5억에서 10억 사이" | min/max 조건 필터링 |
| 카테고리 | "IT 관련 사업?" | 사업명 키워드 검색 |
| 후속 질문 | "그거 언제야?" | 대화 컨텍스트 활용 |

## 🔧 트러블슈팅

### ChromaDB 오류

```bash
# DB 재구축
python scripts/rebuild_db.py
```

### 임베딩 오류

```bash
# API 키 확인
echo $OPENAI_API_KEY
```
