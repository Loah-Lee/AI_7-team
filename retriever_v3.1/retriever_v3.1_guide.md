# retriever_v3.1 가이드

## 1) 개요
`dynamic` 모드는 질의 난이도를 추정해서 리트리버를 선택합니다.

- easy: `hybrid`
- hard: `chroma`

주의: hard 경로는 lexical 혼합 없이 dense(chroma) 우선으로 동작합니다.

## 2) 실행 예시
```bash
python scripts/eval_retrieval.py \
  --retriever dynamic \
  --hybrid-alpha 0.6 \
  --dynamic-hard-threshold 2
```

## 3) 주요 파라미터
- `--hybrid-alpha`: easy 경로의 hybrid 가중치
- `--dynamic-hard-threshold`: hard 판정 임계값

## 4) 현재 구현 파일
- `src/graph/workflow.py`
  - dynamic 라우팅(hybrid/chroma) + weak hybrid fallback
- `scripts/eval_retrieval.py`
  - `--retriever dynamic` 및 관련 파라미터 지원
- `src/retrievers/vectorstore.py`
  - query 난이도 스코어 계산
  - `chroma` / `hybrid` / `dynamic` 검색 모드

## 5) 데이터 경로(현재 dev 기준)
- Chroma DB: `data_index/chroma_B`
- 기본 컬렉션: `chunks` (`CHROMA_COLLECTION` 환경변수로 변경 가능)

## 6) 다음 실험(보류)
- hard query에서 `chroma + lexical` 소량 혼합 비율 탐색
