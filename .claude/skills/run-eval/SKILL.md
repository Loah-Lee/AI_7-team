---
name: run-eval
description: RAG E2E 평가를 실행하고 결과를 요약한다.
allowed-tools: Bash, Read
---

# /run-eval

RAG 평가 파이프라인을 실행하고 결과를 요약합니다.

## 실행 절차

1. 평가 실행:
   ```bash
   uv run python scripts/eval_retrieval.py --label $ARGUMENTS --top_k 5
   ```
   - `$ARGUMENTS`가 없으면 `--label current` 사용

2. 실행 완료 후:
   - 결과 JSON 파일 읽기 (`eval/` 디렉토리에서 가장 최근 파일)
   - 전체 평균 점수 출력 (Correctness, Answer Coverage, Faithfulness, Context Relevance)
   - 유형별 평균 점수 출력 (single_doc, multi_doc, comparison)
   - Retrieval 보조 지표 출력 (Recall@5, MRR)
   - 약점 지표 하이라이트

3. HTML 리포트 생성:
   ```bash
   uv run python scripts/build_eval_report.py
   ```
   - `eval/eval_report.html` 생성 확인
