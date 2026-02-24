# retriever_v3.1

리트리버 단계 산출물 전용 폴더입니다.

## 목적
- preprocessor_v3.1 이후 단계(검색/선별) 작업물을 별도 관리
- 브랜치 머지/푸시 시 리트리버 변경 범위를 명확히 분리

## 현재 범위
- 동적 라우팅 전략: easy query -> hybrid, hard query -> chroma
- hard query 경로에서 lexical 혼합 비활성화(chroma only)

## 관련 코드 위치
- src/graph/workflow.py
- scripts/eval_retrieval.py

## 차후 실험 메모
- hard query에서도 chroma + lexical 소량 혼합 실험 예정
