# METRICS

- Retrieval: `recall@5`, `recall@10`, `mrr`
- Retrieval(보조): `source_recall@10` (문서 단위 일치 확인)
- Answer: `answered_rate`, `grounded_rate`, `type_match_rate`, `exact_match`

해석 규칙:
- `hybrid_alpha=1.0` 실험은 lexical baseline으로 분류한다.
- 벡터 기반 성능 평가는 `hybrid_alpha<1` 또는 `retriever=chroma/dense` 결과와 함께 비교한다.
