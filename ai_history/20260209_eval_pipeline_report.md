# RAG 평가 체계 구축 + Langfuse 트레이싱 연동

**날짜**: 2026-02-09
**브랜치**: feature/integration-eval-yc

---

## 1. User Prompt

PDF 청크 품질 개선 후 "실제로 검색 품질이 올랐는가"를 측정할 방법이 없으므로,
평가셋 생성 → Retrieval 평가 자동화 → Langfuse 점수 기록까지 3단계 평가 체계를 구축.

---

## 2. Thinking Process

### 문제 분석
- 기존 `audit_db.py`는 청크 수준 프록시 지표만 측정 (테이블 비율, 길이 등)
- `src/evaluation/metrics.py`에 `calculate_hit_position` 등이 정의되어 있지만 미사용
- Langfuse 콜백이 LLM 호출에 연결되어 있지만, 평가 점수 기록은 미구현
- **Ground Truth Q&A 쌍 부재** — 가장 큰 gap

### 설계 결정
1. **평가셋 자동 생성**: ChromaDB에서 고품질 청크 샘플링 → LLM이 Q&A 쌍 초안 생성
   - is_toc, is_form, 짧은 텍스트 제외
   - 기관별 균형 샘플링으로 편향 방지
   - 질문 유형 분산: single_doc(60%), multi_doc(20%), comparison(20%)
2. **Retrieval 평가**: source 레벨 매칭 (page 레벨은 청크 분할로 불안정)
   - Recall@K, Hit Rate@K, MRR, Avg Score 4개 지표
   - `--label` 파라미터로 A/B 비교 지원
3. **Langfuse 연동**: generate() 노드에서 trace_id 추출 → AICR + 검색 지표 자동 기록

### 디버깅 이력
- **Bug**: Hit@1이지만 Recall=0 — `calculate_recall_at_k`가 source+page 동시 매칭을 요구
- **원인**: 청크 분할 후 page 번호가 원본과 달라질 수 있음 (특히 HWP)
- **수정**: eval_retrieval.py에서 source 레벨 매칭으로 변경 (page 매칭 제외)

---

## 3. Execution Result

### 변경 파일

| 파일 | 변경 | 라인 |
|---|---|---|
| `scripts/generate_eval_set.py` | **신규** — LLM 기반 평가셋 자동 생성 | 229 |
| `scripts/eval_retrieval.py` | **신규** — Recall@K, MRR 등 자동 측정 | 147 |
| `src/evaluation/metrics.py` | Recall@K, MRR, Hit Rate, Avg Score 함수 추가 | +68 |
| `src/evaluation/langfuse_tracer.py` | `log_retrieval_metrics()` 추가 | +26 |
| `src/graph/nodes.py` | `generate()` 노드에 Langfuse 점수 기록 추가 | +23 |

### Evidence of Execution

**구문 검증 (5개 파일 전체 통과)**:
```
  [OK] scripts/generate_eval_set.py
  [OK] scripts/eval_retrieval.py
  [OK] src/evaluation/metrics.py
  [OK] src/evaluation/langfuse_tracer.py
  [OK] src/graph/nodes.py
```

**Import 체인 검증 (전체 통과)**:
```
[OK] metrics.py imports
[OK] langfuse_tracer.py imports
[OK] nodes.py imports
```

**메트릭 함수 단위 테스트 (전체 통과)**:
```
[OK] recall_at_k
[OK] hit_rate_at_k
[OK] mrr
[OK] avg_score
```

**평가셋 생성 테스트 (3개 Q&A)**:
```
[완료] 3개 Q&A 쌍 생성됨
[저장] eval/eval_dataset.yaml
```

**Retrieval 평가 실행 결과**:
```
  Recall@5:    1.0000
  Hit Rate@5:  1.0000
  MRR:            1.0000
  Avg Score:      0.5393
  Empty Retrieval: 0/3
  소요 시간:       1.5초
```

---

## 4. 실행 방법

```bash
# 1. 평가셋 생성 (기본 20개 Q&A)
uv run python scripts/generate_eval_set.py
# 옵션: --num_pairs 30 --model gpt-5

# 2. 생성된 평가셋 확인
cat eval/eval_dataset.yaml | head -60

# 3. Retrieval 평가 실행
uv run python scripts/eval_retrieval.py --label current --top_k 5

# 4. 결과 확인
cat eval/eval_results_current.json

# 5. A/B 비교 (개선 전/후)
uv run python scripts/eval_retrieval.py --label before --top_k 5
# ... 변경 적용 ...
uv run python scripts/eval_retrieval.py --label after --top_k 5
# → eval/eval_results_before.json vs eval/eval_results_after.json 비교

# 6. Langfuse 대시보드에서 score 확인
# → https://us.cloud.langfuse.com 에서 aicr, retrieval_count, retrieval_avg_score 등 확인
```
