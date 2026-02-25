# USAGE

`workspace_collab` 기준 실행 명령 모음입니다.

## 환경 준비

```bash
cd workspace_collab
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

## 앱 실행

```bash
streamlit run app/main.py
```

## 기본 점검 질문

- 고려대학교 사업비는 얼마인가요?
- 서울특별시의 사업비는?
- 서울시립대학교 정보 알려줘
- 사업비가 가장 많은 3곳은?

## 평가

```bash
python scripts/generate_eval_set.py --num_pairs 20
python scripts/eval_retrieval.py --label collab --top_k 5
```

## 주의사항

- `data_index/chroma_B`가 비어 있으면 첫 실행에 인덱싱 시간이 필요합니다.
- HWP/HWPX 처리를 위해 LibreOffice가 필요합니다.

