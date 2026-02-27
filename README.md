# 입찰메이트 RFP 챗봇 (`workspace_collab`)

`workspace_collab`는 협업용 실행 폴더입니다.

- 질문 유형: 기관 조회, 사업비/일정, 랭킹, 카테고리, 후속질문
- UI: Streamlit (`app/main.py`)
- 벡터 저장소: Chroma (`data_index/chroma_B`)
- 데이터 원본: `data_index/files`

## 1) 클론 후 바로 실행

```bash
git clone -b feature/jh2 https://github.com/Loah-Lee/AI_7-team.git
cd AI_7-team/workspace_collab

# one-shot bootstrap
./scripts/bootstrap.sh

# or manual
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# .env에 OPENAI_API_KEY 설정

streamlit run app/main.py
```

## 2) 첫 실행 시 동작

- 기본 DB 경로는 `workspace_collab/data_index/chroma_B` 입니다.
- 이 경로에 DB가 없으면 `data_index/files`를 기준으로 자동 인덱싱을 수행합니다.
- 인덱싱은 문서량/환경에 따라 시간이 걸릴 수 있습니다.

## 3) 시스템 의존성

HWP/HWPX 처리용으로 LibreOffice가 필요합니다.

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y libreoffice
```

## 4) 자주 쓰는 실행 명령

```bash
# Streamlit
streamlit run app/main.py

# 평가 데이터셋 생성
python scripts/generate_eval_set.py --num_pairs 20

# E2E 평가 실행
python scripts/eval_retrieval.py --label collab --top_k 5
```

## 5) 폴더 구조 (요약)

```text
workspace_collab/
├── app/main.py
├── src/
│   ├── graph/
│   ├── prompts/
│   ├── retrievers/
│   ├── parsers/
│   └── utils/
├── data_index/
│   ├── files/          # 원본 문서
│   └── chroma_B/       # 로컬 Chroma DB (대용량, git 제외)
├── requirements.txt
└── docs/
```

## 6) 트러블슈팅

- `ModuleNotFoundError`: `.venv` 활성화 후 `pip install -r requirements.txt` 재실행
- 느린 응답: UI 사이드바의 `♻️ 챗봇 캐시 초기화` 버튼 실행
- DB 관련 오류: `data_index/chroma_B` 삭제 후 앱 재시작(재인덱싱)
