# Page-Level Recall 활성화

## User Prompt
eval_dataset.yaml에 page 정보가 전부 존재하고 `calculate_recall_at_k()`도 이미 `ground_truth_page` 파라미터를 지원하지만, 호출 시 넘기지 않아 source 레벨로만 매칭되는 문제를 해결. Page-level recall을 병렬로 추가 계산.

## Thinking Process
1. `metrics.py`의 `calculate_hit_position`이 page 파라미터가 없어 source-only 매칭 → page 파라미터 추가
2. `eval_retrieval.py`에서 gt_page 추출 후 page-level recall/hit_position 별도 계산하여 기존 source-level과 병렬 유지
3. summary에 `hit_rate_at_k_page`, `mrr_page` 추가, per_query에 `recall_at_k_page`, `hit_position_page`, `ground_truth_page` 추가
4. HTML 대시보드에 page-level 카드 2개 추가, query card meta-row에 page hit 위치/정답 페이지 표시
5. METRICS.md에 Source vs Page 구분 설명 추가

## Execution Result

### 수정 파일 (4개)

| 파일 | 변경 내용 |
|------|----------|
| `src/evaluation/metrics.py` | `calculate_hit_position`에 `ground_truth_page` 파라미터 추가, source+page 매칭 로직 |
| `scripts/eval_retrieval.py` | gt_page 추출, page-level recall/hit_pos 병렬 계산, summary에 page 지표 추가, 콘솔 출력 개선 |
| `scripts/build_eval_report.py` | HTML 카드에 Hit Rate@5 (Page), MRR (Page) 추가, query card에 page hit 정보 표시 |
| `eval/METRICS.md` | Hit Rate@K, MRR, Recall@K를 Source/Page 레벨로 구분 설명 |

### 검증
- Python syntax check: 3개 파일 모두 통과
- 기존 source-level 지표는 그대로 유지 (하위 호환)
- page-level 지표는 별도 필드로 추가 (기존 JSON 구조 파괴 없음)
