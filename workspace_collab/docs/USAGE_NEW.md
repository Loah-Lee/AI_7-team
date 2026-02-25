# USAGE_NEW

## 1. Clone

```bash
git clone -b feature/jh2 https://github.com/Loah-Lee/AI_7-team.git
cd AI_7-team/workspace_collab
```

## 2. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env
```

`.env`에서 최소 `OPENAI_API_KEY`를 설정합니다.

## 3. Run

```bash
streamlit run app/main.py
```

## 4. 운영 팁

- 코드 변경 후 반영이 늦으면 사이드바 `♻️ 챗봇 캐시 초기화` 버튼을 누르세요.
- `data_index/chroma_B`는 로컬 DB 경로입니다.
- DB가 없을 때는 `data_index/files`로 자동 인덱싱합니다.

## 5. Follow-up 질문 예시

1. `고려대학교 사업비는 얼마인가요?`
2. `마감일은?`

두 번째 질문은 직전 기관 문맥을 유지해서 처리됩니다.

